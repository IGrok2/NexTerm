from __future__ import annotations

import os
import posixpath
import stat
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import paramiko
from PyQt5.QtCore import QFileInfo, QMimeData, Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QFileIconProvider, QHBoxLayout, QHeaderView, QInputDialog, QStyle,
    QMenu, QMessageBox, QSplitter,
    QTableWidgetItem, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import CaptionLabel, CardWidget, FluentIcon as FIF, LineEdit, PrimaryPushButton, ProgressBar, PushButton, StrongBodyLabel, TableWidget, TitleLabel, TreeWidget
from send2trash import send2trash

from .models import Host
from .storage import Store
from .ssh import load_private_key


def human_size(value: int) -> str:
    size=float(value)
    for unit in ("B","KB","MB","GB","TB"):
        if size<1024 or unit=="TB": return f"{size:.0f} {unit}" if unit=="B" else f"{size:.1f} {unit}"
        size/=1024


class FileTree(TreeWidget):
    dropped = pyqtSignal(object, object)
    def __init__(self, side: str, parent=None):
        super().__init__(parent);self.side=side;self.setObjectName("fileTree");self.setHeaderLabels(["Name","Size","Type","Modified","Permissions"])
        self.header().setSectionResizeMode(0,QHeaderView.Stretch)
        for i in range(1,5): self.header().setSectionResizeMode(i,QHeaderView.ResizeToContents)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection); self.setAlternatingRowColors(True); self.setSortingEnabled(True); self.sortByColumn(0,Qt.AscendingOrder)
        self.setDragEnabled(True);self.setAcceptDrops(True);self.setDropIndicatorShown(True);self.setDefaultDropAction(Qt.CopyAction);self.setDragDropMode(QAbstractItemView.DragDrop)
    def startDrag(self,actions):
        items=self.selectedItems()
        if not items:return
        mime=QMimeData();payload=[]
        for item in items:
            data=item.data(0,Qt.UserRole)
            if not data:continue
            payload.append(data[0])
        mime.setData("application/x-nexterm-file-list",("\n".join(payload)).encode("utf-8"))
        mime.setData("application/x-nexterm-side",self.side.encode("ascii"))
        if self.side=="local":mime.setUrls([QUrl.fromLocalFile(path) for path in payload])
        drag=QDrag(self);drag.setMimeData(mime);drag.exec_(Qt.CopyAction)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-nexterm-file-list"):event.acceptProposedAction()
        else:super().dragEnterEvent(event)
    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-nexterm-file-list"):event.acceptProposedAction()
        else:super().dragMoveEvent(event)
    def dropEvent(self,event):
        self.dropped.emit(event.mimeData(),self.itemAt(event.pos()));event.acceptProposedAction()


class TransferWorker(QThread):
    progress=pyqtSignal(int,str); status=pyqtSignal(str); finishedOk=pyqtSignal(bool,str)
    def __init__(self,host:Host,store:Store,direction:str,source:str,target:str):
        super().__init__(); self.host=host; self.store=store; self.direction=direction; self.source=source; self.target=target; self._cancel=threading.Event(); self.client=None
    def cancel(self):
        self._cancel.set()
        if self.client:
            try:self.client.close()
            except Exception:pass
    def _callback(self,done,total):
        if self._cancel.is_set(): raise InterruptedError("Transfer cancelled")
        self.progress.emit(int(done*100/max(1,total)),f"{human_size(done)} / {human_size(total)}")
    def _connect(self):
        c=paramiko.SSHClient(); c.load_system_host_keys(); c.load_host_keys(str(self.store.known_hosts_path)); c.set_missing_host_key_policy(paramiko.RejectPolicy())
        kw=dict(hostname=self.host.hostname,port=self.host.port,username=self.host.username,timeout=15,banner_timeout=15,auth_timeout=15,allow_agent=True,look_for_keys=True)
        if self.host.auth=="key":
            private_key=self.store.private_key(self.host.id);passphrase=self.store.secret(self.host.id,"passphrase")
            if private_key:kw.update(pkey=load_private_key(private_key,passphrase))
            elif self.host.key_path:kw.update(key_filename=self.host.key_path,passphrase=passphrase or None)
        else: kw.update(password=self.store.secret(self.host.id) or None)
        c.connect(**kw); return c
    def run(self):
        try:
            self.client=self._connect(); sftp=self.client.open_sftp()
            if self.direction=="upload": self._upload(sftp,Path(self.source),self.target)
            else:self._download(sftp,self.source,Path(self.target))
            sftp.close();self.finishedOk.emit(True,"Completed")
        except Exception as exc:self.finishedOk.emit(False,str(exc))
        finally:
            if self.client:self.client.close()
    def _upload(self,sftp,local:Path,remote:str):
        if local.is_dir():
            try:sftp.mkdir(remote)
            except IOError:pass
            for child in local.iterdir():self._upload(sftp,child,posixpath.join(remote,child.name))
        else:self.status.emit(local.name);sftp.put(str(local),remote,callback=self._callback)
    def _download(self,sftp,remote:str,local:Path):
        mode=sftp.stat(remote).st_mode
        if stat.S_ISDIR(mode):
            local.mkdir(parents=True,exist_ok=True)
            for name in sftp.listdir(remote):self._download(sftp,posixpath.join(remote,name),local/name)
        else:local.parent.mkdir(parents=True,exist_ok=True);self.status.emit(posixpath.basename(remote));sftp.get(remote,str(local),callback=self._callback)


class SftpPage(QWidget):
    transferFinished=pyqtSignal(str,bool,str)
    def __init__(self,store:Store,parent=None):
        super().__init__(parent);self.setObjectName("sftpPage");self.store=store;self.session=None;self.sftp=None;self.local_path=Path.home();self.remote_path=".";self.jobs=[]
        root=QVBoxLayout(self);root.setContentsMargins(18,14,18,16);root.setSpacing(10)
        title_row=QHBoxLayout();title_row.addWidget(TitleLabel("Files",self));self.connection=CaptionLabel("No SSH session selected",self);title_row.addWidget(self.connection,1)
        self.refresh_btn=PushButton(FIF.SYNC,"Refresh");self.refresh_btn.clicked.connect(self.refresh);title_row.addWidget(self.refresh_btn);root.addLayout(title_row)
        splitter=QSplitter(Qt.Horizontal);self.local_panel,self.local_tree=self._panel("This PC",True);self.remote_panel,self.remote_tree=self._panel("Remote server",False);splitter.addWidget(self.local_panel);splitter.addWidget(self.remote_panel);splitter.setSizes([600,600]);root.addWidget(splitter,1)
        actions=QHBoxLayout();self.upload_btn=PrimaryPushButton(FIF.UP,"Upload →");self.download_btn=PrimaryPushButton(FIF.DOWN,"← Download");self.mkdir_btn=PushButton(FIF.FOLDER_ADD,"New remote folder");self.rename_btn=PushButton(FIF.EDIT,"Rename");self.delete_btn=PushButton(FIF.DELETE,"Delete")
        for w in (self.upload_btn,self.download_btn,self.mkdir_btn,self.rename_btn,self.delete_btn):actions.addWidget(w)
        actions.addStretch();root.addLayout(actions)
        queue_title=StrongBodyLabel("Transfer queue",self);root.addWidget(queue_title)
        self.queue=TableWidget(self);self.queue.setObjectName("transferQueue");self.queue.setColumnCount(5);self.queue.setRowCount(0);self.queue.setHorizontalHeaderLabels(["File","Direction","Destination","Progress","Status"]);self.queue.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.queue.setMinimumHeight(112);self.queue.setMaximumHeight(155);root.addWidget(self.queue)
        self.local_tree.itemDoubleClicked.connect(lambda item,_:self._open_local(item));self.remote_tree.itemDoubleClicked.connect(lambda item,_:self._open_remote(item))
        self.local_tree.dropped.connect(lambda mime,item:self._drop_on_local(mime,item));self.remote_tree.dropped.connect(lambda mime,item:self._drop_on_remote(mime,item))
        self.local_tree.setContextMenuPolicy(Qt.CustomContextMenu);self.local_tree.customContextMenuRequested.connect(lambda p:self._local_menu(p));self.remote_tree.setContextMenuPolicy(Qt.CustomContextMenu);self.remote_tree.customContextMenuRequested.connect(lambda p:self._remote_menu(p))
        self.upload_btn.clicked.connect(self.upload);self.download_btn.clicked.connect(self.download);self.mkdir_btn.clicked.connect(self.remote_mkdir);self.rename_btn.clicked.connect(self.rename_remote);self.delete_btn.clicked.connect(self.delete_remote)
        self.load_local(self.local_path);self._enabled(False)
    def _panel(self,title,local):
        panel=CardWidget(self);panel.setObjectName("filePanel")
        lay=QVBoxLayout(panel);head=QHBoxLayout();label=StrongBodyLabel(title,panel);head.addWidget(label)
        up=PushButton(FIF.UP,"Up");path=LineEdit();path.setClearButtonEnabled(True);go=PushButton("Go");head.addWidget(up);head.addWidget(path,1);head.addWidget(go);lay.addLayout(head);tree=FileTree("local" if local else "remote");lay.addWidget(tree)
        if local:self.local_edit=path;up.clicked.connect(self.local_up);go.clicked.connect(lambda:self.load_local(Path(path.text())));path.returnPressed.connect(lambda:self.load_local(Path(path.text())))
        else:self.remote_edit=path;up.clicked.connect(self.remote_up);go.clicked.connect(lambda:self.load_remote(path.text()));path.returnPressed.connect(lambda:self.load_remote(path.text()))
        return panel,tree
    def _enabled(self,value):
        for w in (self.upload_btn,self.download_btn,self.mkdir_btn,self.rename_btn,self.delete_btn,self.remote_tree,self.remote_edit):w.setEnabled(value)
    def set_session(self,session):
        if self.sftp:
            try:self.sftp.close()
            except Exception:pass
        self.session=session;self.sftp=None
        if not session or not session.client():self.connection.setText("No connected SSH session selected");self._enabled(False);return
        try:self.sftp=session.client().open_sftp();self.connection.setText(f"● {session.host.name}  ·  {session.host.username}@{session.host.hostname}");self._enabled(True);self.load_remote(".")
        except Exception as exc:self.connection.setText(f"SFTP unavailable: {exc}");self._enabled(False)
    def load_local(self,path):
        try:
            path=Path(path).expanduser().resolve();items=[]
            for p in path.iterdir():
                try:
                    s=p.stat();hidden=p.name.startswith(".") or bool(getattr(s,"st_file_attributes",0)&2)
                    if not self.store.data["settings"].get("show_hidden",False) and hidden:continue
                    items.append((not p.is_dir(),p.name,p,s))
                except OSError:pass
            self.local_tree.clear();self.local_path=path;self.local_edit.setText(str(path))
            for _,name,p,s in sorted(items,key=lambda x:(x[0],x[1].lower())):
                folder=p.is_dir();it=QTreeWidgetItem([name,"" if folder else human_size(s.st_size),"Folder" if folder else (p.suffix[1:].upper()+" file" if p.suffix else "File"),datetime.fromtimestamp(s.st_mtime).strftime("%Y-%m-%d %H:%M"),oct(s.st_mode&0o777)]);it.setIcon(0,QFileIconProvider().icon(QFileInfo(str(p))));it.setData(0,Qt.UserRole,(str(p),folder));self.local_tree.addTopLevelItem(it)
        except Exception as exc:QMessageBox.warning(self,"Local files",str(exc))
    def load_remote(self,path):
        if not self.sftp:return
        try:
            path=self.sftp.normalize(path);attrs=self.sftp.listdir_attr(path);self.remote_tree.clear();self.remote_path=path;self.remote_edit.setText(path)
            for a in sorted(attrs,key=lambda a:(not stat.S_ISDIR(a.st_mode),a.filename.lower())):
                if not self.store.data["settings"].get("show_hidden",False) and a.filename.startswith("."):continue
                folder=stat.S_ISDIR(a.st_mode);remote=posixpath.join(path,a.filename);it=QTreeWidgetItem([a.filename,"" if folder else human_size(a.st_size),"Folder" if folder else "File",datetime.fromtimestamp(a.st_mtime).strftime("%Y-%m-%d %H:%M"),oct(a.st_mode&0o777)]);it.setIcon(0,QApplication.style().standardIcon(QStyle.SP_DirIcon if folder else QStyle.SP_FileIcon));it.setData(0,Qt.UserRole,(remote,folder,a.filename));self.remote_tree.addTopLevelItem(it)
        except Exception as exc:QMessageBox.warning(self,"Remote files",str(exc))
    def refresh(self):
        self.load_local(self.local_path)
        if self.session and self.session.client() and self.sftp:
            self.load_remote(self.remote_path)
        elif self.session:
            self.set_session(None)
    def local_up(self):self.load_local(self.local_path.parent)
    def remote_up(self):self.load_remote(posixpath.dirname(self.remote_path) or "/")
    def _open_local(self,item):
        path,folder=item.data(0,Qt.UserRole)
        if folder:self.load_local(path)
        else:
            try:os.startfile(path)
            except OSError as exc:QMessageBox.warning(self,"Open file",str(exc))
    def _open_remote(self,item):
        path,folder,name=item.data(0,Qt.UserRole)
        if folder:self.load_remote(path)
        else:
            cache=Path(tempfile.gettempdir())/"NexTerm"/"remote-cache"/self.session.host.id/name
            self._queue_job("download",path,str(cache),open_after=True)
    def upload(self):
        if not self.session:return
        for item in self.local_tree.selectedItems():
            path,folder=item.data(0,Qt.UserRole);self._queue_job("upload",path,posixpath.join(self.remote_path,Path(path).name))
    def download(self):
        if not self.session:return
        for item in self.remote_tree.selectedItems():
            path,folder,name=item.data(0,Qt.UserRole);self._queue_job("download",path,str(self.local_path/name))
    def _drop_target_remote(self,item):
        if item:
            data=item.data(0,Qt.UserRole)
            if data and data[1]:return data[0]
        return self.remote_path
    def _drop_target_local(self,item):
        if item:
            data=item.data(0,Qt.UserRole)
            if data and data[1]:return Path(data[0])
        return self.local_path
    def _drop_on_remote(self,mime,item):
        if not self.session:return
        target_dir=self._drop_target_remote(item)
        paths=[]
        if mime.hasUrls():paths=[url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        elif mime.data("application/x-nexterm-side").data().decode("ascii",errors="ignore")=="local":paths=mime.data("application/x-nexterm-file-list").data().decode("utf-8",errors="ignore").splitlines()
        for path in paths:
            if path:self._queue_job("upload",path,posixpath.join(target_dir,Path(path).name))
    def _drop_on_local(self,mime,item):
        if not self.session:return
        if mime.data("application/x-nexterm-side").data().decode("ascii",errors="ignore")!="remote":return
        target_dir=self._drop_target_local(item)
        for remote in mime.data("application/x-nexterm-file-list").data().decode("utf-8",errors="ignore").splitlines():
            if remote:self._queue_job("download",remote,str(target_dir/posixpath.basename(remote)))
    def _queue_job(self,direction,source,target,open_after=False):
        row=self.queue.rowCount();self.queue.insertRow(row);name=Path(source).name if direction=="upload" else posixpath.basename(source)
        for col,text in enumerate([name,"Upload" if direction=="upload" else "Download",target,"","Queued"]):self.queue.setItem(row,col,QTableWidgetItem(text))
        progress=ProgressBar(self);progress.setRange(0,100);self.queue.setCellWidget(row,3,progress);job=TransferWorker(self.session.host,self.store,direction,source,target);job.open_after=open_after;self.jobs.append(job)
        job.progress.connect(lambda value,text,r=row,p=progress:(p.setValue(value),p.setFormat(text+" · %p%")));job.status.connect(lambda text,r=row:self.queue.item(r,4).setText("Transferring · "+text));job.finishedOk.connect(lambda ok,msg,r=row,j=job:self._job_done(r,j,ok,msg));job.start()
    def _job_done(self,row,job,ok,msg):
        self.queue.item(row,4).setText("Completed" if ok else "Failed · "+msg);self.jobs=[j for j in self.jobs if j is not job]
        name=Path(job.source).name if job.direction=="upload" else posixpath.basename(job.source);self.transferFinished.emit(name,ok,msg)
        if ok:
            self.refresh()
            if job.open_after:
                try:os.startfile(job.target)
                except OSError as exc:QMessageBox.warning(self,"Open file",str(exc))
    def remote_mkdir(self):
        name,ok=QInputDialog.getText(self,"New remote folder","Folder name")
        if ok and name and self.sftp:
            try:self.sftp.mkdir(posixpath.join(self.remote_path,name));self.load_remote(self.remote_path)
            except Exception as exc:QMessageBox.warning(self,"New folder",str(exc))
    def rename_remote(self):
        item=self.remote_tree.currentItem()
        if not item or not self.sftp:return
        old,_,name=item.data(0,Qt.UserRole);new,ok=QInputDialog.getText(self,"Rename","New name",text=name)
        if ok and new:
            try:self.sftp.rename(old,posixpath.join(self.remote_path,new));self.load_remote(self.remote_path)
            except Exception as exc:QMessageBox.warning(self,"Rename",str(exc))
    def delete_remote(self):
        items=self.remote_tree.selectedItems()
        if not items or not self.sftp:return
        if QMessageBox.question(self,"Delete remote items",f"Permanently delete {len(items)} selected item(s)?")!=QMessageBox.Yes:return
        try:
            for item in items:
                path,folder,_=item.data(0,Qt.UserRole);self._remote_remove(path,folder)
            self.load_remote(self.remote_path)
        except Exception as exc:QMessageBox.warning(self,"Delete",str(exc))
    def _remote_remove(self,path,folder):
        if folder:
            for a in self.sftp.listdir_attr(path):self._remote_remove(posixpath.join(path,a.filename),stat.S_ISDIR(a.st_mode))
            self.sftp.rmdir(path)
        else:self.sftp.remove(path)
    def _local_menu(self,pos):
        item=self.local_tree.itemAt(pos)
        if not item:return
        if not item.isSelected():self.local_tree.setCurrentItem(item)
        path,folder=item.data(0,Qt.UserRole);menu=QMenu(self);open_item=menu.addAction("Open");open_item.setEnabled(not folder);upload=menu.addAction("Upload to server");rename=menu.addAction("Rename");trash=menu.addAction("Move to Recycle Bin");action=menu.exec_(self.local_tree.viewport().mapToGlobal(pos))
        if action==open_item:self._open_local(item)
        elif action==upload:self.upload()
        elif item and action==rename:
            path,_=item.data(0,Qt.UserRole);new,ok=QInputDialog.getText(self,"Rename","New name",text=Path(path).name)
            if ok and new:Path(path).rename(Path(path).with_name(new));self.load_local(self.local_path)
        elif item and action==trash:
            path,_=item.data(0,Qt.UserRole)
            if QMessageBox.question(self,"Recycle",f"Move {Path(path).name} to Recycle Bin?")==QMessageBox.Yes:send2trash(path);self.load_local(self.local_path)
    def _remote_menu(self,pos):
        item=self.remote_tree.itemAt(pos)
        if item and not item.isSelected():self.remote_tree.setCurrentItem(item)
        if not item:self.remote_tree.clearSelection()
        menu=QMenu(self);open_item=menu.addAction("Open");download=menu.addAction("Download");menu.addSeparator();rename=menu.addAction("Rename");mkdir=menu.addAction("New folder");delete=menu.addAction("Delete permanently")
        is_file=bool(item and not item.data(0,Qt.UserRole)[1]);open_item.setEnabled(is_file)
        for selection_action in (download,rename,delete):selection_action.setEnabled(item is not None)
        action=menu.exec_(self.remote_tree.viewport().mapToGlobal(pos))
        if action==open_item:self._open_remote(item)
        elif action==download:self.download()
        elif action==rename:self.rename_remote()
        elif action==mkdir:self.remote_mkdir()
        elif action==delete:self.delete_remote()
    def shutdown(self):
        for job in self.jobs:job.cancel()
        for job in self.jobs:job.wait(3000)
        if self.sftp:
            try:self.sftp.close()
            except Exception:pass
