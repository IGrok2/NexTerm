from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QColorDialog, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QHeaderView, QMenu, QMessageBox, QShortcut, QStackedWidget, QSystemTrayIcon, QTableWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, ComboBox, FluentIcon as FIF, FluentWindow, IconWidget, InfoBar, InfoBarPosition, LineEdit,
    NavigationItemPosition, PrimaryPushButton, PushButton, ScrollArea, SearchLineEdit, SpinBox, TabBar,
    StrongBodyLabel, SubtitleLabel, SwitchButton, TableWidget, Theme, TitleLabel, TransparentToolButton,
    isDarkTheme, setTheme, setThemeColor,
)

from app import __version__
from app.dialogs import DeleteGroupDialog, GroupDialog, HostDialog, MoveGroupDialog, SnippetDialog, TunnelDialog
from app.discord_rpc import DiscordRpc
from app.importers import backup_termius_profile, discover_termius_exports, import_hosts, import_termius_local
from app.license_manager import validate_license
from app.models import Host, Snippet
from app.ssh import ReverseTunnelServer
from app.sftp import SftpPage
from app.storage import Store
from app.system_integration import check_github_version, set_autostart
from app.terminal import TerminalSession


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("pageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(3)
        layout.addWidget(TitleLabel(title, self))
        caption = BodyLabel(subtitle, self)
        caption.setObjectName("pageSubtitle")
        caption.setWordWrap(True)
        layout.addWidget(caption)


class EmptyState(CardWidget):
    def __init__(self, icon, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 46, 24, 46)
        layout.setSpacing(8)
        glyph = IconWidget(icon, self)
        glyph.setFixedSize(42, 42)
        layout.addWidget(glyph, 0, Qt.AlignHCenter)
        heading = SubtitleLabel(title, self)
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)
        text = BodyLabel(detail, self)
        text.setObjectName("pageSubtitle")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text)


class HostCard(CardWidget):
    connectRequested = pyqtSignal(object)
    editRequested = pyqtSignal(object)
    moveRequested = pyqtSignal(object)

    def __init__(self, host: Host):
        super().__init__(); self.host = host; self.setObjectName("hostCard")
        self.setCursor(Qt.PointingHandCursor); self.setMinimumHeight(104); self.setMaximumHeight(112)
        row = QHBoxLayout(self); row.setContentsMargins(14, 13, 10, 13); row.setSpacing(12)
        accent=QWidget(self);accent.setFixedWidth(4);accent.setStyleSheet(f"background: {host.color}; border-radius: 2px;")
        row.addWidget(accent)
        icon=IconWidget(FIF.PIN if host.favorite else FIF.CLOUD,self);icon.setFixedSize(36,36)
        texts=QVBoxLayout();texts.setSpacing(3)
        name=StrongBodyLabel(host.name,self)
        name.setToolTip(host.name)
        meta=CaptionLabel(f"{host.username}@{host.hostname}:{host.port}",self)
        meta.setToolTip(meta.text())
        tag_text=", ".join(host.tags[:3])
        group=CaptionLabel((host.group or "Ungrouped") + (f"  -  {tag_text}" if tag_text else ""),self);group.setObjectName("hostGroup")
        texts.addWidget(name);texts.addWidget(meta);texts.addWidget(group)
        actions=QVBoxLayout();actions.setSpacing(2)
        connect=TransparentToolButton(FIF.CONNECT,self);connect.setToolTip("Connect");connect.setFixedSize(32,32);connect.clicked.connect(lambda:self.connectRequested.emit(host));actions.addWidget(connect)
        edit=TransparentToolButton(FIF.EDIT,self);edit.setToolTip("Edit host");edit.setFixedSize(32,32);edit.clicked.connect(lambda:self.editRequested.emit(host));actions.addWidget(edit)
        row.addWidget(icon);row.addLayout(texts,1);row.addLayout(actions)

    def mouseDoubleClickEvent(self, event): self.connectRequested.emit(self.host)
    def contextMenuEvent(self,event):
        menu=QMenu(self);connect=menu.addAction("Connect");edit=menu.addAction("Edit");move=menu.addAction("Move to group")
        action=menu.exec_(event.globalPos())
        if action==connect:self.connectRequested.emit(self.host)
        elif action==edit:self.editRequested.emit(self.host)
        elif action==move:self.moveRequested.emit(self.host)


class GroupFolderCard(CardWidget):
    openRequested = pyqtSignal(str)
    renameRequested = pyqtSignal(str)
    deleteRequested = pyqtSignal(str)

    def __init__(self, group: str, hosts: list[Host]):
        super().__init__();self.group=group;self.setObjectName("hostCard");self.setCursor(Qt.PointingHandCursor);self.setMinimumHeight(92);self.setMaximumHeight(104)
        row=QHBoxLayout(self);row.setContentsMargins(14,13,12,13);row.setSpacing(12)
        icon=IconWidget(FIF.FOLDER,self);icon.setFixedSize(38,38);row.addWidget(icon)
        texts=QVBoxLayout();texts.setSpacing(3)
        title=StrongBodyLabel(group,self);title.setToolTip(group);texts.addWidget(title)
        total=len(hosts);favorites=sum(1 for h in hosts if h.favorite)
        detail=CaptionLabel(f"{total} host{'s' if total!=1 else ''}" + (f"  -  {favorites} pinned" if favorites else ""),self);detail.setObjectName("hostGroup");texts.addWidget(detail)
        sample=", ".join(h.name for h in sorted(hosts,key=lambda h:h.name.lower())[:3])
        hint=CaptionLabel(sample or "Empty group",self);hint.setObjectName("hostGroup");hint.setToolTip(sample);texts.addWidget(hint)
        actions=QVBoxLayout();actions.setSpacing(2)
        edit=TransparentToolButton(FIF.EDIT,self);edit.setToolTip("Rename group");edit.setFixedSize(30,30);edit.clicked.connect(lambda:self.renameRequested.emit(group));actions.addWidget(edit)
        delete=TransparentToolButton(FIF.DELETE,self);delete.setToolTip("Delete group");delete.setFixedSize(30,30);delete.clicked.connect(lambda:self.deleteRequested.emit(group));actions.addWidget(delete)
        row.addLayout(texts,1);row.addLayout(actions)

    def mouseDoubleClickEvent(self,event):self.openRequested.emit(self.group)
    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if event.button()==Qt.LeftButton:self.openRequested.emit(self.group)


class HostsPage(QWidget):
    connectHost = pyqtSignal(object); editHost = pyqtSignal(object); newHost = pyqtSignal()
    def __init__(self, store: Store):
        super().__init__(); self.setObjectName("hostsPage"); self.store=store
        root=QVBoxLayout(self); root.setContentsMargins(28,24,28,28); root.setSpacing(16)
        heading=QHBoxLayout();heading.addWidget(PageHeader("Hosts","Connect to a saved server or import entries from OpenSSH config.",self),1)
        imp=PushButton(FIF.DOWNLOAD,"Import",self);imp.setToolTip("Import OpenSSH or Termius export");imp.clicked.connect(self.import_hosts)
        termius=PushButton(FIF.CLOUD_DOWNLOAD,"Import Termius",self);termius.setToolTip("Import hosts from the local Termius app data")
        termius.clicked.connect(self.import_termius)
        folder=PushButton(FIF.FOLDER_ADD,"New group",self);folder.clicked.connect(self.new_folder)
        add=PrimaryPushButton(FIF.ADD,"New host",self);add.clicked.connect(self.newHost)
        heading.addWidget(imp,0,Qt.AlignTop);heading.addWidget(termius,0,Qt.AlignTop);heading.addWidget(folder,0,Qt.AlignTop);heading.addWidget(add,0,Qt.AlignTop);root.addLayout(heading)
        top=QHBoxLayout(); self.search=SearchLineEdit(); self.search.setPlaceholderText("Search hosts, addresses, users, groups or tags")
        self.search.textChanged.connect(self.refresh)
        self.group_filter=ComboBox(self);self.group_filter.setMinimumWidth(170);self.group_filter.addItem("All groups");self.group_filter.currentTextChanged.connect(self.refresh)
        self.only_favorites=SwitchButton(self);self.only_favorites.setText("Favorites");self.only_favorites.checkedChanged.connect(self.refresh)
        top.addWidget(self.search,1);top.addWidget(self.group_filter);top.addWidget(self.only_favorites);self.summary=CaptionLabel("",self);top.addWidget(self.summary);root.addLayout(top)
        scroll=ScrollArea(); scroll.setWidgetResizable(True);scroll.enableTransparentBackground()
        self.content=QWidget();self.content.setObjectName("hostsContent"); self.grid=QGridLayout(self.content);self.grid.setContentsMargins(0,0,0,0);self.grid.setAlignment(Qt.AlignTop); self.grid.setHorizontalSpacing(12);self.grid.setVerticalSpacing(12);self._columns=4;self._resize_pending=False
        scroll.setWidget(self.content); root.addWidget(scroll,1); self.refresh()

    def refresh(self):
        while self.grid.count():
            item=self.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        all_hosts=self.store.hosts
        groups=["All groups"]+self.store.folders
        current=self.group_filter.currentText() or "All groups"
        self.group_filter.blockSignals(True);self.group_filter.clear();self.group_filter.addItems(groups);self.group_filter.setCurrentText(current if current in groups else "All groups");self.group_filter.blockSignals(False)
        query=self.search.text().lower().strip(); hosts=all_hosts
        if query: hosts=[h for h in hosts if query in " ".join([h.name,h.hostname,h.username,h.group,*h.tags]).lower()]
        selected_group=self.group_filter.currentText()
        if selected_group and selected_group!="All groups":hosts=[h for h in hosts if (h.group or "Ungrouped")==selected_group]
        if self.only_favorites.isChecked():hosts=[h for h in hosts if h.favorite]
        host_word="host" if len(hosts)==1 else "hosts";group_count=len(set(h.group for h in hosts));group_word="group" if group_count==1 else "groups"
        self.summary.setText(f"{len(hosts)} {host_word}  ·  {group_count} {group_word}")
        if not hosts and not (not query and not self.only_favorites.isChecked() and (not selected_group or selected_group=="All groups") and self.store.folders):
            detail="No matches. Try a different search." if query else "Add a server or import your OpenSSH config to get started."
            empty=EmptyState(FIF.SEARCH if query else FIF.CLOUD,"Nothing here yet" if not query else "No matching hosts",detail,self.content)
            self.grid.addWidget(empty,0,0,1,self._columns); return
        if not query and not self.only_favorites.isChecked() and (not selected_group or selected_group=="All groups"):
            folders={group:[h for h in hosts if (h.group or "Ungrouped")==group] for group in self.store.folders}
            label=StrongBodyLabel("Groups",self.content);label.setContentsMargins(0,8,0,2);self.grid.addWidget(label,0,0,1,self._columns)
            row=1
            for i,(group,members) in enumerate(folders.items()):
                card=GroupFolderCard(group,members);card.openRequested.connect(self._open_group);card.renameRequested.connect(self.rename_folder);card.deleteRequested.connect(self.delete_folder)
                self.grid.addWidget(card,row+i//self._columns,i%self._columns)
            for c in range(self._columns): self.grid.setColumnStretch(c,1)
            return
        sections=[]
        favorites=[h for h in hosts if h.favorite]
        if favorites:sections.append(("Favorites",favorites))
        for group in sorted({h.group for h in hosts}):
            members=[h for h in hosts if h.group==group and not h.favorite]
            if members:sections.append((group,members))
        row=0
        for section,members in sections:
            label=StrongBodyLabel(section,self.content);label.setContentsMargins(0,8,0,2);self.grid.addWidget(label,row,0,1,self._columns);row+=1
            for i,host in enumerate(sorted(members,key=lambda h:h.name.lower())):
                card=HostCard(host); card.connectRequested.connect(self.connectHost); card.editRequested.connect(self.editHost);card.moveRequested.connect(self.move_host)
                self.grid.addWidget(card,row+i//self._columns,i%self._columns)
            row+=(len(members)+self._columns-1)//self._columns
        for c in range(self._columns): self.grid.setColumnStretch(c,1)
    def _open_group(self,group):
        self.group_filter.setCurrentText(group);self.refresh()
    def new_folder(self):
        dialog=GroupDialog(self)
        if not dialog.exec():return
        name=dialog.value()
        folders=self.store.folders
        if name.casefold() in {f.casefold() for f in folders}:QMessageBox.information(self,"Group","This group already exists.");return
        self.store.set_folders(folders+[name])
        self.refresh();self.group_filter.setCurrentText(name);self.refresh()
    def rename_folder(self,old):
        if old=="Ungrouped":QMessageBox.information(self,"Group","Ungrouped cannot be renamed.");return
        dialog=GroupDialog(self,old)
        if not dialog.exec():return
        new=dialog.value()
        if not new or new==old:return
        if new.casefold() in {f.casefold() for f in self.store.folders}:QMessageBox.information(self,"Group","This group already exists.");return
        self.store.set_folders([new if f==old else f for f in self.store.folders])
        hosts=self.store.hosts
        for host in hosts:
            if (host.group or "Ungrouped")==old:host.group=new
        self.store.set_hosts(hosts)
        self.refresh();self.group_filter.setCurrentText(new);self.refresh()
    def delete_folder(self,group):
        if group=="Ungrouped":QMessageBox.information(self,"Group","Ungrouped cannot be deleted.");return
        hosts=self.store.hosts;count=sum(1 for h in hosts if (h.group or "Ungrouped")==group)
        if not DeleteGroupDialog(group,count,self).exec():return
        for host in hosts:
            if (host.group or "Ungrouped")==group:host.group="Ungrouped"
        self.store.set_hosts(hosts);self.store.set_folders([f for f in self.store.folders if f!=group])
        self.refresh();self.group_filter.setCurrentText("All groups");self.refresh()
    def move_host(self,host):
        folders=self.store.folders
        current=max(0,folders.index(host.group) if host.group in folders else 0)
        dialog=MoveGroupDialog(host.name,folders,current,self)
        if not dialog.exec():return
        folder=dialog.value()
        hosts=self.store.hosts
        for item in hosts:
            if item.id==host.id:item.group=folder
        self.store.set_hosts(hosts);self.refresh()
    def resizeEvent(self,event):
        super().resizeEvent(event);columns=max(1,min(4,(event.size().width()-56)//300))
        if columns!=self._columns:
            self._columns=columns
            if not self._resize_pending:self._resize_pending=True;QTimer.singleShot(80,self._finish_resize)
    def _finish_resize(self):self._resize_pending=False;self.refresh()

    def import_hosts(self):
        default=str(Path.home()/".ssh"/"config")
        path,_=QFileDialog.getOpenFileName(self,"Import hosts",default,"Supported files (*.json *.csv config);;Termius export (*.json *.csv);;OpenSSH config (config);;All files (*)")
        if not path: return
        try:
            hosts=self.store.hosts;existing={h.name.casefold() for h in hosts};count=0;key_count=0
            for host in import_hosts(path):
                if not host.hostname or host.name.casefold() in existing:continue
                if host.auth=="key" and host.key_path and Path(host.key_path).expanduser().is_file():
                    try:self.store.set_private_key(host.id,str(Path(host.key_path).expanduser()));key_count+=1
                    except OSError:pass
                hosts.append(host);existing.add(host.name.casefold());count+=1
            if not count:InfoBar.info("Nothing imported","No new supported host entries were found.",parent=self,position=InfoBarPosition.TOP_RIGHT);return
            detail=f"Added {count} hosts"
            if key_count:detail+=f" and {key_count} encrypted private keys"
            self.store.set_hosts(hosts);self.store.set_folders(self.store.folders+[h.group for h in hosts]);self.refresh();InfoBar.success("Import complete",detail+". Passwords were not imported.",parent=self,position=InfoBarPosition.TOP_RIGHT)
        except Exception as exc: QMessageBox.warning(self,"Import failed",str(exc))
    def import_termius(self):
        try:
            backup_path,copied,skipped=backup_termius_profile(self.store.imports_path/"termius-backups")
            candidates=[]
            for path in discover_termius_exports()[:10]:
                try:candidates.extend(import_hosts(path))
                except Exception:pass
            ssh_config=Path.home()/".ssh"/"config"
            if ssh_config.exists():
                try:candidates.extend(import_hosts(ssh_config))
                except Exception:pass
            candidates.extend(import_termius_local())
            hosts=self.store.hosts;existing={(h.name.casefold(),h.hostname.casefold(),h.username.casefold(),h.port) for h in hosts};added=0;key_count=0
            for host in candidates:
                key=(host.name.casefold(),host.hostname.casefold(),host.username.casefold(),host.port)
                if not host.hostname or key in existing:continue
                if host.auth=="key" and host.key_path and Path(host.key_path).expanduser().is_file():
                    try:self.store.set_private_key(host.id,str(Path(host.key_path).expanduser()));key_count+=1
                    except OSError:pass
                hosts.append(host);existing.add(key);added+=1
            if not added:
                detail="No new hosts were found."
                if backup_path:detail+=f" Termius profile backup copied {copied} files."
                InfoBar.info("Termius migration",detail,parent=self,position=InfoBarPosition.TOP_RIGHT);return
            self.store.set_hosts(hosts);self.store.set_folders(self.store.folders+[h.group for h in hosts]);self.refresh()
            detail=f"Added {added} hosts"
            if key_count:detail+=f", encrypted {key_count} private keys"
            if backup_path:detail+=f", backed up {copied} Termius files"
            if skipped:detail+=f" ({skipped} locked skipped)"
            InfoBar.success("Termius migration",detail+". Passwords from encrypted Termius storage were not imported.",parent=self,position=InfoBarPosition.TOP_RIGHT)
        except Exception as exc:QMessageBox.warning(self,"Termius import failed",str(exc))


class TerminalPage(QWidget):
    sftpRequested = pyqtSignal(object)
    sessionChanged = pyqtSignal(object)
    sessionState = pyqtSignal(object,str,str)
    def __init__(self, store: Store):
        super().__init__(); self.setObjectName("terminalPage"); self.store=store
        root=QVBoxLayout(self); root.setContentsMargins(24,20,24,24);root.setSpacing(10)
        bar=QHBoxLayout();bar.addWidget(PageHeader("Terminal","Interactive SSH sessions",self),1)
        self.reconnect=PushButton(FIF.SYNC,"Reconnect");self.sftp=PushButton(FIF.FOLDER,"SFTP")
        for icon,tip,action in ((FIF.COPY,"Copy selection",self.copy_current),(FIF.PASTE,"Paste",self.paste_current),(FIF.BROOM,"Clear terminal",self.clear_current),(FIF.ZOOM_OUT,"Zoom out",lambda:self.zoom_current(-1)),(FIF.ZOOM_IN,"Zoom in",lambda:self.zoom_current(1))):
            button=TransparentToolButton(icon,self);button.setToolTip(tip);button.setFixedSize(32,32);button.clicked.connect(action);bar.addWidget(button)
        self.close=TransparentToolButton(FIF.CLOSE,self);self.close.setToolTip("Close tab");self.close.setFixedSize(32,32)
        bar.addWidget(self.reconnect);bar.addWidget(self.sftp);bar.addWidget(self.close);root.addLayout(bar)
        self.status=CaptionLabel("No active session",self);self.status.setObjectName("sessionStatus");root.addWidget(self.status)
        self.tabBar=TabBar(self);self.tabBar.setTabsClosable(True);self.tabBar.setMovable(True);self.tabBar.setAddButtonVisible(False);root.addWidget(self.tabBar)
        self.stack=QStackedWidget(self);root.addWidget(self.stack,1)
        self.tabBar.tabCloseRequested.connect(self.close_tab);self.tabBar.currentChanged.connect(self._select_tab);self.tabBar.tabMoved.connect(self._move_tab); self.close.clicked.connect(lambda:self.close_tab(self.tabBar.currentIndex()))
        self.reconnect.clicked.connect(self.reconnect_current); self.sftp.clicked.connect(self.open_sftp)
        self.placeholder=EmptyState(FIF.COMMAND_PROMPT,"No terminal sessions","Open a host from the Hosts page to start an SSH session.",self)
        self.stack.addWidget(self.placeholder)

    def open_host(self,host:Host):
        if self.stack.indexOf(self.placeholder)>=0:self.stack.removeWidget(self.placeholder);self.placeholder.hide()
        session=TerminalSession(host,self.store); session.stateChanged.connect(lambda state,msg,s=session:self._state(s,state,msg))
        session.route_key=f"{host.id}-{id(session)}";idx=self.stack.addWidget(session);self.tabBar.addTab(session.route_key,host.name,FIF.COMMAND_PROMPT);self.tabBar.setCurrentIndex(idx);self.stack.setCurrentIndex(idx)

    def _state(self,session,state,msg):
        self.sessionState.emit(session,state,msg)
        if session is self.current():self.status.setText(msg)
        idx=self.stack.indexOf(session)
        if idx>=0:self.tabBar.setTabText(idx,("● " if state=="connected" else "○ ")+session.host.name)
    def current(self):
        w=self.stack.currentWidget(); return w if isinstance(w,TerminalSession) else None
    def sessions(self):return [self.stack.widget(i) for i in range(self.stack.count()) if isinstance(self.stack.widget(i),TerminalSession)]
    def _select_tab(self,index):
        if 0<=index<self.stack.count():self.stack.setCurrentIndex(index)
        session=self.current()
        self.status.setText(getattr(session,"status_message","No active session") if session else "No active session")
        self.sessionChanged.emit(session)
    def _move_tab(self,source,target):
        if source==target or source<0 or target<0:return
        widget=self.stack.widget(source);self.stack.removeWidget(widget);self.stack.insertWidget(target,widget);self.stack.setCurrentIndex(target)
    def reconnect_current(self):
        s=self.current()
        if s: s.reconnect()
    def copy_current(self):
        session=self.current()
        if session:session.view.copy()
    def paste_current(self):
        session=self.current()
        if session:session.view.paste_to_remote()
    def clear_current(self):
        session=self.current()
        if session:session.view.clear_terminal()
    def zoom_current(self,delta):
        session=self.current()
        if session:session.view.zoom(delta)
    def open_sftp(self):
        s=self.current()
        if not s or not s.worker or not s.worker.client: QMessageBox.information(self,"SFTP","Connect to a host first."); return
        self.sftpRequested.emit(s)
    def close_tab(self,index):
        if index<0:return
        w=self.stack.widget(index)
        if isinstance(w,TerminalSession): w.close_session()
        self.stack.removeWidget(w);self.tabBar.removeTab(index);w.deleteLater()
        if not self.sessions():self.placeholder.show();self.stack.addWidget(self.placeholder);self.stack.setCurrentWidget(self.placeholder);self.status.setText("No active session")
    def close_all(self):
        for i in range(self.tabBar.count()-1,-1,-1): self.close_tab(i)


class DataPage(QWidget):
    addRequested=pyqtSignal();runSnippet=pyqtSignal(object);editSnippet=pyqtSignal(object);deleteSnippet=pyqtSignal(object);toggleTunnel=pyqtSignal(object);editTunnel=pyqtSignal(object);deleteTunnel=pyqtSignal(object)
    def __init__(self,store:Store,kind:str):
        super().__init__(); self.store=store; self.kind=kind; self.setObjectName(kind+"Page")
        root=QVBoxLayout(self); root.setContentsMargins(28,24,28,28);root.setSpacing(14)
        titles={"snippets":("Snippets","Run reusable commands in the active terminal."),"tunnels":("TCP tunnels","Expose local web apps, game servers or any TCP service through your VPS IP."),"history":("Connection history","Recent successful and failed connection attempts."),"known":("Known hosts","Trusted SSH host keys saved by NexTerm."),"keychain":("SSH keys","Private keys configured for saved hosts.")}
        row=QHBoxLayout();title,subtitle=titles[kind];row.addWidget(PageHeader(title,subtitle,self),1)
        if kind in ("snippets","tunnels"):
            add=PrimaryPushButton(FIF.ADD,"Add"); add.clicked.connect(self.addRequested); row.addWidget(add)
        if kind=="snippets":
            run=PushButton(FIF.COMMAND_PROMPT,"Run");run.clicked.connect(self._run_selected);row.addWidget(run)
            edit=PushButton(FIF.EDIT,"Edit");edit.clicked.connect(self._edit_selected);row.addWidget(edit)
            delete=PushButton(FIF.DELETE,"Delete");delete.clicked.connect(self._delete_snippet);row.addWidget(delete)
        if kind=="tunnels":
            toggle=PushButton(FIF.POWER_BUTTON,"Start / Stop");toggle.clicked.connect(self._toggle_tunnel_selected);row.addWidget(toggle)
            edit=PushButton(FIF.EDIT,"Edit");edit.clicked.connect(self._edit_tunnel);row.addWidget(edit)
            delete=PushButton(FIF.DELETE,"Delete");delete.clicked.connect(self._delete_tunnel);row.addWidget(delete)
        root.addLayout(row); self.table=TableWidget();self.table.setObjectName("dataTable");self.table.setAlternatingRowColors(True);self.table.setBorderVisible(True);self.table.setWordWrap(False);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.verticalHeader().hide();self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); root.addWidget(self.table); self.refresh()
        if kind=="snippets": self.table.cellDoubleClicked.connect(self._run)
        if kind=="tunnels": self.table.cellDoubleClicked.connect(self._toggle_tunnel)

    def refresh(self):
        if self.kind=="snippets":
            vals=self.store.snippets; headers=["Name","Group","Description","Command"]; rows=[[x.name,x.group,x.description,x.command] for x in vals]
        elif self.kind=="tunnels":
            hosts={h.id:h for h in self.store.hosts}; vals=self.store.tunnels; headers=["Name","Public TCP endpoint","Local target","VPS","Persistent","Status"]; rows=[[x.name,f"{x.public_host or (hosts[x.host_id].hostname if x.host_id in hosts else 'missing')}:{x.remote_port}",f"{x.local_host}:{x.local_port}",hosts[x.host_id].name if x.host_id in hosts else "Missing","Yes" if x.persistent else "No","Running" if x.enabled else "Stopped"] for x in vals]
        elif self.kind=="history":
            vals=self.store.data["history"]; headers=["Time","Host","Address","Status","Details"]; rows=[[x.get(k,"") for k in ("time","host","address","status","detail")] for x in vals]
        elif self.kind=="keychain":
            vals=self.store.hosts
            headers=["Host","Authentication","Source","Protected by"]
            rows=[[x.name,"Private key" if x.auth=="key" else "Password",("Encrypted offline copy" if self.store.has_private_key(x.id) else x.key_path) if x.auth=="key" else "Saved credential",("Windows DPAPI" if self.store.has_private_key(x.id) else "File permissions") if x.auth=="key" else "Windows Credential Manager"] for x in vals]
        else:
            headers=["Host key entry"]; path=self.store.known_hosts_path; rows=[[line.strip()] for line in path.read_text(errors="replace").splitlines()] if path.exists() else []
        self.table.setColumnCount(len(headers)); self.table.setHorizontalHeaderLabels(headers); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row): self.table.setItem(r,c,QTableWidgetItem(str(value)))
    def _run(self,row,_):
        vals=self.store.snippets
        if 0<=row<len(vals): self.runSnippet.emit(vals[row])
    def _run_selected(self):
        item=self._selected_snippet()
        if item:self.runSnippet.emit(item)
        else:InfoBar.info("Select a snippet","Choose a command snippet first.",parent=self,position=InfoBarPosition.TOP_RIGHT)
    def _edit_selected(self):
        item=self._selected_snippet()
        if item:self.editSnippet.emit(item)
        else:InfoBar.info("Select a snippet","Choose a command snippet to edit.",parent=self,position=InfoBarPosition.TOP_RIGHT)
    def _delete_snippet(self):
        item=self._selected_snippet()
        if item:self.deleteSnippet.emit(item)
        else:InfoBar.info("Select a snippet","Choose a command snippet to delete.",parent=self,position=InfoBarPosition.TOP_RIGHT)
    def _selected_snippet(self):
        row=self.table.currentRow();vals=self.store.snippets
        return vals[row] if 0<=row<len(vals) else None
    def _selected_tunnel(self):
        row=self.table.currentRow();vals=self.store.tunnels
        return vals[row] if 0<=row<len(vals) else None
    def _toggle_tunnel(self,row,_):
        vals=self.store.tunnels
        if 0<=row<len(vals):self.toggleTunnel.emit(vals[row])
    def _toggle_tunnel_selected(self):
        item=self._selected_tunnel()
        if item:self.toggleTunnel.emit(item)
        else:InfoBar.info("Select a tunnel","Choose a TCP tunnel first.",parent=self,position=InfoBarPosition.TOP_RIGHT)
    def _edit_tunnel(self):
        item=self._selected_tunnel()
        if item:self.editTunnel.emit(item)
        else:InfoBar.info("Select a tunnel","Choose a TCP tunnel to edit.",parent=self,position=InfoBarPosition.TOP_RIGHT)
    def _delete_tunnel(self):
        item=self._selected_tunnel()
        if item:self.deleteTunnel.emit(item)
        else:InfoBar.info("Select a tunnel","Choose a TCP tunnel to delete.",parent=self,position=InfoBarPosition.TOP_RIGHT)


class SettingsPage(QWidget):
    changed=pyqtSignal()
    def __init__(self,store:Store):
        super().__init__(); self.setObjectName("settingsPage"); self.store=store; s=store.data["settings"]
        scroll=ScrollArea();scroll.setWidgetResizable(True);scroll.enableTransparentBackground();content=QWidget();content.setObjectName("settingsContent");content.setAttribute(Qt.WA_StyledBackground,True);root=QVBoxLayout(content);root.setContentsMargins(28,24,28,28);root.setSpacing(14)
        root.addWidget(PageHeader("Settings","Personalize NexTerm and control connection behavior.",self))
        self.theme=ComboBox(); self.theme.addItems(["System","Light","Dark"]); self.theme.setCurrentText(s.get("theme","Dark"))
        self.palette=ComboBox();self.palette.addItems(["NexTerm Blue","Graphite","Emerald","Crimson","Violet"]);self.palette.setCurrentText(s.get("palette","NexTerm Blue"));self.palette.currentTextChanged.connect(self.apply_palette)
        self.accent=PushButton(s.get("accent","#0A84FF")); self.accent.clicked.connect(lambda:self.pick("accent",self.accent))
        self.bg=PushButton(s.get("terminal_bg","#0F1220")); self.bg.clicked.connect(lambda:self.pick("terminal_bg",self.bg))
        self.fg=PushButton(s.get("terminal_fg","#D7E0EA")); self.fg.clicked.connect(lambda:self.pick("terminal_fg",self.fg))
        self.opacity=SpinBox(self);self.opacity.setRange(45,100);self.opacity.setSuffix(" %");self.opacity.setValue(int(s.get("window_opacity",100)))
        self.font=ComboBox(); self.font.addItems(["Cascadia Mono","JetBrains Mono","Consolas","Courier New"]); self.font.setCurrentText(s.get("font","Cascadia Mono"))
        self.font_size=SpinBox(self); self.font_size.setRange(12,32); self.font_size.setValue(max(12,int(s.get("font_size",12))))
        self.scrollback=SpinBox(self); self.scrollback.setRange(1000,100000); self.scrollback.setSingleStep(1000); self.scrollback.setSuffix(" lines"); self.scrollback.setValue(int(s.get("scrollback",10000)))
        self.keepalive=SpinBox(self); self.keepalive.setRange(0,300); self.keepalive.setSuffix(" seconds"); self.keepalive.setValue(int(s.get("keepalive",30)))
        self.reconnect=SwitchButton(); self.reconnect.setChecked(bool(s.get("reconnect",True)))
        self.copy_select=SwitchButton(); self.copy_select.setChecked(bool(s.get("copy_on_select",False)))
        self.confirm=SwitchButton(); self.confirm.setChecked(bool(s.get("confirm_close",True)))
        self.cursor_blink=SwitchButton(); self.cursor_blink.setChecked(bool(s.get("cursor_blink",True)))
        self.mica=SwitchButton(); self.mica.setChecked(bool(s.get("mica",True)))
        self.autostart=SwitchButton();self.autostart.setChecked(bool(s.get("autostart",False)))
        self.hidden=SwitchButton(); self.hidden.setChecked(bool(s.get("show_hidden",False)))
        self.in_app_notifications=SwitchButton();self.in_app_notifications.setChecked(bool(s.get("in_app_notifications",True)))
        self.system_notifications=SwitchButton();self.system_notifications.setChecked(bool(s.get("system_notifications",False)))
        self.sound_notifications=SwitchButton();self.sound_notifications.setChecked(bool(s.get("sound_notifications",False)))
        self.discord_rpc=SwitchButton();self.discord_rpc.setChecked(bool(s.get("discord_rpc",False)))
        self.discord_client_id=LineEdit();self.discord_client_id.setPlaceholderText("Discord Application ID");self.discord_client_id.setText(str(s.get("discord_client_id",Store.DEFAULT_DISCORD_CLIENT_ID)))
        self.discord_details=LineEdit();self.discord_details.setMaxLength(128);self.discord_details.setText(s.get("discord_details","Взламывает Пентагон"))
        self.github_repo=LineEdit();self.github_repo.setPlaceholderText("owner/repository");self.github_repo.setText(str(s.get("github_repo","Ilja/NexTerm")))
        self.version_label=CaptionLabel(f"Installed version: {__version__}",self)
        self.check_updates=PushButton(FIF.SYNC,"Check GitHub release",self);self.check_updates.clicked.connect(self.check_update)
        self.license_key=LineEdit();self.license_key.setPlaceholderText("Enterprise activation code");self.license_key.setText(str(s.get("license_key","")))
        self.license_label=CaptionLabel(f"{s.get('license_edition','Standard')} / {s.get('license_status','active')}",self)
        self.activate_license=PushButton(FIF.ACCEPT,"Activate license",self);self.activate_license.clicked.connect(self.activate)
        root.addWidget(self._card("Appearance",(("App theme",self.theme),("Color palette",self.palette),("Windows accent",self.accent),("Window opacity",self.opacity),("Windows 11 Mica effect",self.mica))))
        root.addWidget(self._card("Terminal",(("Background",self.bg),("Text color",self.fg),("Font",self.font),("Font size",self.font_size),("Scrollback",self.scrollback),("Blinking cursor",self.cursor_blink),("Copy selected text",self.copy_select))))
        root.addWidget(self._card("System",(("Start with Windows",self.autostart),("Check updates from",self.github_repo),("Version",self.version_label),("",self.check_updates))))
        root.addWidget(self._card("Connections and files",(("SSH keepalive",self.keepalive),("Reconnect automatically",self.reconnect),("Show hidden SFTP files",self.hidden),("Confirm before closing sessions",self.confirm))))
        root.addWidget(self._card("Notifications",(("Show alerts in NexTerm",self.in_app_notifications),("Show Windows notifications",self.system_notifications),("Play sound",self.sound_notifications))))
        root.addWidget(self._card("License",(("Edition",self.license_label),("Activation code",self.license_key),("",self.activate_license))))
        root.addWidget(self._card("Discord Rich Presence",(("Enable Discord RPC",self.discord_rpc),("Application ID",self.discord_client_id),("Activity text",self.discord_details))))
        note=CaptionLabel("Passwords and key passphrases are stored in Windows Credential Manager. Other data stays in %APPDATA%\\NexTerm.",self);note.setWordWrap(True);root.addWidget(note)
        actions=QHBoxLayout();actions.addStretch();save=PrimaryPushButton(FIF.SAVE,"Save and apply");save.clicked.connect(self.save);actions.addWidget(save);root.addLayout(actions);root.addStretch()
        for button in (self.accent,self.bg,self.fg):self._update_color_button(button)
        scroll.setWidget(content);layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(scroll)
    def _card(self,title,rows):
        card=CardWidget(self);card.setObjectName("settingsCard");layout=QVBoxLayout(card);layout.setContentsMargins(20,16,20,18);layout.setSpacing(12);layout.addWidget(StrongBodyLabel(title,card));form=QFormLayout();form.setHorizontalSpacing(28);form.setVerticalSpacing(12);form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow);form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        for label,widget in rows:form.addRow(label,widget)
        layout.addLayout(form);return card
    def _update_color_button(self,button):
        swatch=QPixmap(16,16);swatch.fill(QColor(button.text()));button.setIcon(QIcon(swatch))
    def pick(self,key,button):
        value=QColorDialog.getColor(QColor(button.text()),self,"Choose color")
        if value.isValid():button.setText(value.name().upper());self._update_color_button(button)
    def apply_palette(self,name):
        palettes={
            "NexTerm Blue":("#0067C0","#0B0F14","#D7DEE8"),
            "Graphite":("#7A7F87","#121212","#F2F2F2"),
            "Emerald":("#168A55","#08120D","#DDF7E8"),
            "Crimson":("#C42B47","#17080C","#FFE1E7"),
            "Violet":("#7C4DFF","#100B1F","#ECE6FF"),
        }
        accent,bg,fg=palettes.get(name,palettes["NexTerm Blue"])
        self.accent.setText(accent);self.bg.setText(bg);self.fg.setText(fg)
        for button in (self.accent,self.bg,self.fg):self._update_color_button(button)
    def check_update(self):
        try:
            has_update,latest,url=check_github_version(self.github_repo.text().strip(),__version__)
            if has_update:
                if QMessageBox.question(self,"Update available",f"NexTerm {latest} is available. Open GitHub releases?")==QMessageBox.Yes:QDesktopServices.openUrl(QUrl(url))
            else:InfoBar.success("Up to date",f"NexTerm {__version__} is the latest release.",parent=self,position=InfoBarPosition.TOP_RIGHT)
        except Exception as exc:QMessageBox.warning(self,"Update check failed",str(exc))
    def activate(self):
        state=validate_license(self.license_key.text(),self.store.license_cache_path)
        s=self.store.data["settings"];s["license_key"]=state.key;s["license_edition"]=state.edition;s["license_status"]=state.status;self.store.save()
        self.license_label.setText(f"{state.edition} / {state.status}")
        if state.edition.casefold()=="enterprise" and state.status in {"active","trial","offline"}:InfoBar.success("License",state.message,parent=self,position=InfoBarPosition.TOP_RIGHT)
        else:InfoBar.warning("License",state.message,parent=self,position=InfoBarPosition.TOP_RIGHT)
    def save(self):
        s=self.store.data["settings"]; s.update(theme=self.theme.currentText(),palette=self.palette.currentText(),accent=self.accent.text(),terminal_bg=self.bg.text(),terminal_fg=self.fg.text(),window_opacity=self.opacity.value(),font=self.font.currentText(),font_size=self.font_size.value(),scrollback=self.scrollback.value(),keepalive=self.keepalive.value(),reconnect=self.reconnect.isChecked(),copy_on_select=self.copy_select.isChecked(),confirm_close=self.confirm.isChecked(),cursor_blink=self.cursor_blink.isChecked(),mica=self.mica.isChecked(),autostart=self.autostart.isChecked(),show_hidden=self.hidden.isChecked(),in_app_notifications=self.in_app_notifications.isChecked(),system_notifications=self.system_notifications.isChecked(),sound_notifications=self.sound_notifications.isChecked(),github_repo=self.github_repo.text().strip(),discord_rpc=self.discord_rpc.isChecked(),discord_client_id=self.discord_client_id.text().strip(),discord_details=self.discord_details.text().strip(),license_key=self.license_key.text().strip())
        try:set_autostart(self.autostart.isChecked())
        except Exception as exc:QMessageBox.warning(self,"Autostart",str(exc))
        self.store.save(); apply_theme(s); self.changed.emit(); InfoBar.success("Saved","Personalization applied",parent=self,position=InfoBarPosition.TOP_RIGHT)


def apply_theme(settings):
    themes={"Dark":Theme.DARK,"Light":Theme.LIGHT,"System":Theme.AUTO}
    name=settings.get("theme","System");setTheme(themes.get(name,Theme.AUTO));setThemeColor(QColor(settings.get("accent","#0067C0")))
    dark=isDarkTheme();surface="#202020" if dark else "#F9F9F9";card="#2B2B2B" if dark else "#FFFFFF";border="#3D3D3D" if dark else "#E5E5E5";muted="#A0A0A0" if dark else "#616161";hover="#323232" if dark else "#F5F5F5";text_color="#FFFFFF" if dark else "#202020";selection=settings.get('accent','#0067C0')
    app=QApplication.instance()
    if app:
        app.setStyleSheet(f"""
            FluentWindow, #hostsPage, #terminalPage, #sftpPage, #keychainPage, #tunnelsPage,
            #snippetsPage, #knownPage, #historyPage, #settingsPage {{ background: {surface}; }}
            #hostsContent {{ background: transparent; }}
            #settingsContent {{ background: {surface}; }}
            #pageSubtitle, #sessionStatus, #hostGroup {{ color: {muted}; }}
            CardWidget#hostCard, CardWidget#emptyState, CardWidget#settingsCard {{
                background: {card}; border: 1px solid {border}; border-radius: 8px;
            }}
            CardWidget#filePanel {{ background: {card}; border: 1px solid {border}; border-radius: 8px; }}
            CardWidget#hostCard:hover {{ background: {hover}; border-color: {settings.get('accent','#0067C0')}; }}
            CardWidget#settingsCard QLabel, CardWidget#filePanel QLabel {{ color: {text_color}; }}
            QTreeWidget#fileTree, QTableWidget#transferQueue {{
                background-color: {card}; alternate-background-color: {hover}; color: {text_color};
                border: 1px solid {border}; border-radius: 4px; selection-background-color: {selection};
            }}
            QTreeWidget#fileTree::item {{ min-height: 28px; border: 0; }}
            QTreeWidget#fileTree QHeaderView::section, QTableWidget#transferQueue QHeaderView::section {{
                background: {hover}; color: {text_color}; border: 0; border-bottom: 1px solid {border}; padding: 6px;
            }}
            QPlainTextEdit#terminalView {{ border: 1px solid {border}; border-radius: 8px; padding: 2px; }}
            QPlainTextEdit#terminalView QScrollBar:vertical {{
                background: transparent; width: 12px; margin: 8px 3px 8px 0;
            }}
            QPlainTextEdit#terminalView QScrollBar::handle:vertical {{
                background: {muted}; border-radius: 4px; min-height: 34px;
            }}
            QPlainTextEdit#terminalView QScrollBar::handle:vertical:hover {{
                background: {settings.get('accent','#0067C0')};
            }}
            QPlainTextEdit#terminalView QScrollBar::add-line:vertical,
            QPlainTextEdit#terminalView QScrollBar::sub-line:vertical,
            QPlainTextEdit#terminalView QScrollBar::add-page:vertical,
            QPlainTextEdit#terminalView QScrollBar::sub-page:vertical {{
                border: 0; background: transparent; height: 0;
            }}
            QSplitter::handle {{ background: {border}; width: 1px; }}
            QToolTip {{ background: {card}; color: {'#FFFFFF' if dark else '#202020'}; border: 1px solid {border}; padding: 5px; }}
        """)


class MainWindow(FluentWindow):
    def __init__(self):
        self.store=Store()
        stale_tunnels=self.store.tunnels
        if any(rule.enabled and not rule.persistent for rule in stale_tunnels):
            for rule in stale_tunnels:
                if not rule.persistent:rule.enabled=False
            self.store.set_tunnels(stale_tunnels)
        apply_theme(self.store.data["settings"]); super().__init__()
        self.setWindowTitle("NexTerm");self.resize(1380,860);self.setMinimumSize(980,640)
        self.tray=QSystemTrayIcon(FIF.COMMAND_PROMPT.icon(),self);self.tray.setToolTip("NexTerm");self.tray.activated.connect(self.restore_from_tray)
        self.discord=DiscordRpc(self);self.discord.statusChanged.connect(self.discord_status)
        self._apply_window_effects()
        self.navigationInterface.setExpandWidth(205)
        if hasattr(self.navigationInterface,"expand"):
            try:self.navigationInterface.expand(useAni=False)
            except TypeError:self.navigationInterface.expand()
        self.hosts=HostsPage(self.store); self.terminal=TerminalPage(self.store); self.sftp=SftpPage(self.store); self.keychain=DataPage(self.store,"keychain"); self.snippets=DataPage(self.store,"snippets"); self.tunnels=DataPage(self.store,"tunnels"); self.known=DataPage(self.store,"known"); self.history=DataPage(self.store,"history"); self.settings=SettingsPage(self.store)
        for page in (self.hosts,self.terminal,self.sftp,self.keychain,self.snippets,self.tunnels,self.known,self.history,self.settings):
            page.setAttribute(Qt.WA_StyledBackground,True)
        self.addSubInterface(self.hosts,FIF.CLOUD,"Hosts"); self.addSubInterface(self.terminal,FIF.COMMAND_PROMPT,"Terminal"); self.addSubInterface(self.sftp,FIF.FOLDER,"SFTP Files"); self.addSubInterface(self.keychain,FIF.FINGERPRINT,"Keychain"); self.addSubInterface(self.snippets,FIF.CODE,"Snippets"); self.addSubInterface(self.tunnels,FIF.LINK,"TCP tunnels"); self.addSubInterface(self.known,FIF.CERTIFICATE,"Known hosts")
        self.addSubInterface(self.history,FIF.HISTORY,"Logs",NavigationItemPosition.BOTTOM); self.addSubInterface(self.settings,FIF.SETTING,"Settings",NavigationItemPosition.BOTTOM)
        self.hosts.newHost.connect(self.new_host); self.hosts.editHost.connect(self.edit_host); self.hosts.connectHost.connect(self.connect_host)
        self.snippets.addRequested.connect(self.new_snippet);self.snippets.runSnippet.connect(self.run_snippet);self.snippets.editSnippet.connect(self.edit_snippet);self.snippets.deleteSnippet.connect(self.delete_snippet);self.tunnels.addRequested.connect(self.new_tunnel);self.tunnels.toggleTunnel.connect(self.toggle_tunnel);self.tunnels.editTunnel.connect(self.edit_tunnel);self.tunnels.deleteTunnel.connect(self.delete_tunnel);self.settings.changed.connect(self.apply_terminal_settings)
        self.terminal.sftpRequested.connect(self.open_sftp_page)
        self.terminal.sessionState.connect(self.refresh_runtime_pages)
        self.sftp.transferFinished.connect(self.transfer_finished)
        self.tunnel_servers={}
        self.install_shortcuts()
        self.apply_notification_settings()
        self.apply_discord_settings()
        self.refresh_license_state()
        QTimer.singleShot(300,self.auto_import_termius)
        QTimer.singleShot(800,self.start_persistent_tunnels)

    def _apply_window_effects(self):
        settings=self.store.data["settings"]
        if hasattr(self,"setMicaEffectEnabled"): self.setMicaEffectEnabled(bool(settings.get("mica",True)))
        self.setWindowOpacity(max(0.45,min(1.0,int(settings.get("window_opacity",100))/100)))

    def install_shortcuts(self):
        self.shortcuts=[]
        for sequence,callback in (
            ("Ctrl+N",self.new_host),
            ("Ctrl+K",self.focus_host_search),
            ("Ctrl+W",lambda:self.terminal.close_tab(self.terminal.tabBar.currentIndex())),
            ("F5",self.refresh_current_page),
        ):
            shortcut=QShortcut(QKeySequence(sequence),self);shortcut.activated.connect(callback);self.shortcuts.append(shortcut)

    def focus_host_search(self):
        self.switchTo(self.hosts);self.hosts.search.setFocus();self.hosts.search.selectAll()

    def refresh_current_page(self):
        page=self.stackedWidget.currentWidget() if hasattr(self,"stackedWidget") else None
        if hasattr(page,"refresh"):page.refresh()
        elif page is self.sftp:self.sftp.refresh()

    def auto_import_termius(self):
        imported=set(self.store.data.get("auto_imported",[]));paths=[p for p in discover_termius_exports() if str(p) not in imported]
        if not paths:return
        hosts=self.store.hosts;existing={(h.name.casefold(),h.hostname.casefold(),h.username.casefold(),h.port) for h in hosts};added=0;used=[]
        for path in paths[:5]:
            try:candidates=import_hosts(path)
            except Exception:continue
            path_added=0
            for host in candidates:
                key=(host.name.casefold(),host.hostname.casefold(),host.username.casefold(),host.port)
                if not host.hostname or key in existing:continue
                hosts.append(host);existing.add(key);added+=1;path_added+=1
            if path_added:used.append(str(path))
        if used:
            self.store.set_hosts(hosts);self.store.set_folders(self.store.folders+[h.group for h in hosts]);self.store.data["auto_imported"]=sorted(imported.union(used));self.store.save();self.hosts.refresh();self.keychain.refresh()
            self.notify("Termius import",f"Imported {added} hosts from {len(used)} export file(s).","success")

    def restore_from_tray(self,reason):
        if reason in (QSystemTrayIcon.Trigger,QSystemTrayIcon.DoubleClick):
            self.showNormal();self.raise_();self.activateWindow()

    def new_host(self):
        dlg=HostDialog(self)
        if dlg.exec_():
            host,pw,pp=dlg.value()
            if not self.save_private_key(host):return
            hosts=self.store.hosts; hosts.append(host); self.store.set_hosts(hosts); self.store.set_folders(self.store.folders+[host.group]); self.store.set_secret(host.id,pw); self.store.set_secret(host.id,pp,"passphrase"); self.hosts.refresh(); self.keychain.refresh()
    def edit_host(self,host):
        dlg=HostDialog(self,host)
        result=dlg.exec_()
        if result and dlg.delete_requested:
            if QMessageBox.question(self,"Delete host",f"Delete {host.name} and its stored credentials?")==QMessageBox.Yes:
                for rule_id,server in list(self.tunnel_servers.items()):
                    rule=next((item for item in self.store.tunnels if item.id==rule_id),None)
                    if rule and rule.host_id==host.id:server.stop();self.tunnel_servers.pop(rule_id,None)
                self.store.set_tunnels([r for r in self.store.tunnels if r.host_id!=host.id]);self.store.set_hosts([h for h in self.store.hosts if h.id!=host.id]);self.store.delete_secret(host.id);self.hosts.refresh();self.keychain.refresh();self.tunnels.refresh()
        elif result:
            updated,pw,pp=dlg.value()
            if not self.save_private_key(updated):return
            hosts=[updated if h.id==updated.id else h for h in self.store.hosts]; self.store.set_hosts(hosts); self.store.set_folders(self.store.folders+[updated.group]); self.store.set_secret(updated.id,pw); self.store.set_secret(updated.id,pp,"passphrase"); self.hosts.refresh(); self.keychain.refresh()
    def save_private_key(self,host):
        if host.auth!="key":self.store.delete_private_key(host.id);return True
        path=Path(host.key_path).expanduser()
        if not path.is_file():
            if self.store.has_private_key(host.id):return True
            QMessageBox.warning(self,"Private key","Select an existing private key file.");return False
        try:self.store.set_private_key(host.id,str(path));return True
        except Exception as exc:QMessageBox.warning(self,"Private key",f"Could not store an encrypted offline copy.\n\n{exc}");return False
    def connect_host(self,host):
        self.terminal.open_host(host); self.switchTo(self.terminal)
    def open_sftp_page(self,session):
        self.sftp.set_session(session);self.switchTo(self.sftp)
    def refresh_runtime_pages(self,session,state,message):
        self.known.refresh();self.history.refresh()
        if self.sftp.session and not self.sftp.session.client():self.sftp.set_session(None)
        if state=="connected":self.notify("Connected",f"{session.host.name} · {session.host.username}@{session.host.hostname}","success")
        elif state=="error":self.notify("Connection failed",f"{session.host.name}: {message}","error")
    def new_snippet(self):
        dlg=SnippetDialog(self)
        if dlg.exec_(): vals=self.store.snippets; vals.append(dlg.value()); self.store.set_snippets(vals); self.snippets.refresh()
    def edit_snippet(self,snippet):
        dlg=SnippetDialog(self,snippet)
        if dlg.exec_():
            updated=dlg.value();vals=[updated if item.id==updated.id else item for item in self.store.snippets];self.store.set_snippets(vals);self.snippets.refresh()
    def delete_snippet(self,snippet):
        if QMessageBox.question(self,"Delete snippet",f"Delete {snippet.name}?")!=QMessageBox.Yes:return
        self.store.set_snippets([item for item in self.store.snippets if item.id!=snippet.id]);self.snippets.refresh()
    def run_snippet(self,snippet):
        session=self.terminal.current()
        if not session: QMessageBox.information(self,"Snippet","Open an SSH session first."); return
        session.send_command(snippet.command); self.switchTo(self.terminal)
    def new_tunnel(self):
        hosts=self.store.hosts
        if not hosts: QMessageBox.information(self,"TCP tunnel","Add a VPS host first."); return
        dlg=TunnelDialog(hosts,self)
        if dlg.exec_(): vals=self.store.tunnels; vals.append(dlg.value()); self.store.set_tunnels(vals); self.tunnels.refresh()
    def edit_tunnel(self,rule):
        was_running=rule.id in self.tunnel_servers
        if was_running:self.stop_tunnel(rule)
        dlg=TunnelDialog(self.store.hosts,self,rule)
        if dlg.exec_():
            updated=dlg.value();vals=[updated if item.id==updated.id else item for item in self.store.tunnels];self.store.set_tunnels(vals);self.tunnels.refresh()
            if was_running:self.start_tunnel(updated)
    def delete_tunnel(self,rule):
        if QMessageBox.question(self,"Delete tunnel",f"Delete {rule.name}?")!=QMessageBox.Yes:return
        self.stop_tunnel(rule)
        self.store.set_tunnels([item for item in self.store.tunnels if item.id!=rule.id]);self.tunnels.refresh()
    def toggle_tunnel(self,rule):
        if rule.id in self.tunnel_servers:self.stop_tunnel(rule)
        else:self.start_tunnel(rule)
    def start_persistent_tunnels(self):
        for rule in self.store.tunnels:
            if rule.enabled and rule.persistent and rule.id not in self.tunnel_servers:self.start_tunnel(rule,quiet=True)
    def start_tunnel(self,rule,quiet=False):
        host=next((item for item in self.store.hosts if item.id==rule.host_id),None)
        if not host:
            if not quiet:QMessageBox.warning(self,"TCP tunnel","The selected VPS host is missing.")
            return
        try:
            server=ReverseTunnelServer(host,rule,self.store.secret(host.id),self.store.secret(host.id,"passphrase"),int(self.store.data["settings"].get("keepalive",30)),str(self.store.known_hosts_path),self.store.private_key(host.id))
            server.status.connect(lambda state,message,rid=rule.id:self.tunnel_status(rid,state,message))
            self.tunnel_servers[rule.id]=server;rule.enabled=True;self.store.set_tunnels([rule if x.id==rule.id else x for x in self.store.tunnels]);self.tunnels.refresh();server.start()
        except Exception as exc:
            self.tunnel_servers.pop(rule.id,None);rule.enabled=False;self.store.set_tunnels([rule if x.id==rule.id else x for x in self.store.tunnels]);self.tunnels.refresh()
            if not quiet:QMessageBox.warning(self,"TCP tunnel",str(exc))
    def stop_tunnel(self,rule):
        server=self.tunnel_servers.pop(rule.id,None)
        if server:server.stop();server.wait(2000)
        rule.enabled=False;self.store.set_tunnels([rule if x.id==rule.id else x for x in self.store.tunnels]);self.tunnels.refresh()
    def tunnel_status(self,rule_id,state,message):
        if state=="running":self.notify("Tunnel online",message,"success")
        elif state=="warning":self.notify("Tunnel warning",message,"error")
        elif state=="error":
            self.notify("Tunnel failed",message,"error")
            self.tunnel_servers.pop(rule_id,None)
            vals=[]
            for item in self.store.tunnels:
                if item.id==rule_id:item.enabled=False
                vals.append(item)
            self.store.set_tunnels(vals);self.tunnels.refresh()
        elif state=="stopped":
            self.tunnel_servers.pop(rule_id,None);self.tunnels.refresh()
    def transfer_finished(self,name,ok,message):
        self.notify("Transfer complete" if ok else "Transfer failed",name if ok else f"{name}: {message}","success" if ok else "error")
    def apply_notification_settings(self):
        enabled=bool(self.store.data["settings"].get("system_notifications",False)) and QSystemTrayIcon.isSystemTrayAvailable()
        self.tray.show() if enabled else self.tray.hide()
    def apply_discord_settings(self):
        settings=self.store.data["settings"];self.discord.configure(bool(settings.get("discord_rpc",False)),str(settings.get("discord_client_id","")),str(settings.get("discord_details","Взламывает Пентагон")))
    def discord_status(self,connected,message):
        if self.store.data["settings"].get("discord_rpc",False):self.notify("Discord RPC" if connected else "Discord RPC unavailable",message,"success" if connected else "error")
    def notify(self,title,message,level="info"):
        settings=self.store.data["settings"]
        visible=self.isVisible() and not self.isMinimized()
        if settings.get("in_app_notifications",True) and visible:
            factory={"success":InfoBar.success,"error":InfoBar.error}.get(level,InfoBar.info)
            factory(title,message,parent=self,position=InfoBarPosition.TOP_RIGHT,duration=4000)
        important=level in ("error","success") or "Tunnel" in title or not visible
        if (settings.get("system_notifications",True) or important) and QSystemTrayIcon.isSystemTrayAvailable():
            icon=QSystemTrayIcon.Critical if level=="error" else QSystemTrayIcon.Information
            if not self.tray.isVisible():self.tray.show()
            self.tray.showMessage(title,message,icon,5000)
        if settings.get("sound_notifications",False):QApplication.beep()
    def refresh_license_state(self):
        key=str(self.store.data["settings"].get("license_key","")).strip()
        if not key:return
        state=validate_license(key,self.store.license_cache_path)
        self.store.data["settings"]["license_edition"]=state.edition
        self.store.data["settings"]["license_status"]=state.status
        self.store.save()
        if hasattr(self,"settings"):self.settings.license_label.setText(f"{state.edition} / {state.status}")
    def apply_terminal_settings(self):
        self._apply_window_effects()
        self.apply_notification_settings()
        self.apply_discord_settings()
        self.sftp.refresh()
        for w in self.terminal.sessions():
            if isinstance(w,TerminalSession): w.view.apply_settings(self.store.data["settings"])
    def closeEvent(self,event):
        persistent_running=any(rule.persistent and rule.id in self.tunnel_servers for rule in self.store.tunnels)
        if persistent_running:
            self.tray.show();self.hide();event.ignore();self.notify("NexTerm is still running","Persistent tunnels are active in the system tray.","info");return
        active=any(session.client() for session in self.terminal.sessions())
        if active and self.store.data["settings"].get("confirm_close") and QMessageBox.question(self,"Close NexTerm","Close all active SSH sessions?")!=QMessageBox.Yes: event.ignore(); return
        self.terminal.close_all()
        self.sftp.shutdown()
        for server in self.tunnel_servers.values(): server.stop();server.wait(2000)
        self.discord.stop()
        self.tray.hide()
        event.accept()


def main():
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR","1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication(sys.argv); app.setApplicationName("NexTerm"); app.setOrganizationName("NexTerm")
    app.setWindowIcon(FIF.COMMAND_PROMPT.icon())
    app.setFont(QFont("Segoe UI Variable",10)); window=MainWindow(); window.show(); sys.exit(app.exec_())


if __name__=="__main__": main()
