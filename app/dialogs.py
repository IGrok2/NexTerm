from __future__ import annotations

from pathlib import Path

from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import QColorDialog, QFileDialog, QFormLayout, QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CheckBox, ComboBox, FluentIcon as FIF, LineEdit, MessageBoxBase,
    PasswordLineEdit, PushButton, SpinBox, SubtitleLabel,
)

from .models import Host, Snippet, TunnelRule


class FluentForm(MessageBoxBase):
    def begin(self, title: str, width: int = 500):
        self.titleLabel = SubtitleLabel(title, self); self.viewLayout.addWidget(self.titleLabel)
        self.formWidget = QWidget(self); self.form = QFormLayout(self.formWidget); self.form.setSpacing(12); self.form.setContentsMargins(0, 4, 0, 4)
        self.viewLayout.addWidget(self.formWidget); self.widget.setMinimumWidth(width); self.yesButton.setText("Save"); self.cancelButton.setText("Cancel")


class HostDialog(FluentForm):
    def __init__(self, parent=None, host: Host | None = None):
        super().__init__(parent); self.host=host; self.delete_requested=False; self.begin("Edit SSH host" if host else "New SSH host",540)
        self.name=LineEdit(self);self.name.setPlaceholderText("Production node")
        self.address=LineEdit(self);self.address.setPlaceholderText("server.example.com or 2001:db8::1")
        self.user=LineEdit(self);self.user.setPlaceholderText("root")
        self.port=SpinBox(self);self.port.setRange(1,65535);self.port.setValue(22)
        self.group=LineEdit(self);self.group.setPlaceholderText("nodes")
        self.tags=LineEdit(self);self.tags.setPlaceholderText("prod, docker, eu-west")
        self.color=PushButton("#0A84FF",self);self.color.clicked.connect(self._pick_color)
        self.auth=ComboBox(self);self.auth.addItems(["Password","Private key"])
        self.password=PasswordLineEdit(self);self.password.setPlaceholderText("Stored in Windows Credential Manager")
        key_row=QWidget(self);key_layout=QHBoxLayout(key_row);key_layout.setContentsMargins(0,0,0,0);self.key_path=LineEdit(self);self.key_path.setPlaceholderText("C:\\Users\\you\\.ssh\\id_ed25519");self.browse=PushButton(FIF.FOLDER,"Browse",self);self.browse.clicked.connect(self._browse);key_layout.addWidget(self.key_path);key_layout.addWidget(self.browse)
        self.passphrase=PasswordLineEdit(self);self.passphrase.setPlaceholderText("Optional")
        self.favorite=CheckBox("Pin to Favorites",self)
        for label,widget in (("Name",self.name),("Hostname / IP",self.address),("Username",self.user),("Port",self.port),("Group",self.group),("Tags",self.tags),("Accent color",self.color),("Authentication",self.auth),("Password",self.password),("Private key",key_row),("Key passphrase",self.passphrase),("",self.favorite)):self.form.addRow(label,widget)
        if host:
            self.name.setText(host.name);self.address.setText(host.hostname);self.user.setText(host.username);self.port.setValue(host.port);self.group.setText(host.group);self.tags.setText(", ".join(host.tags));self.color.setText(host.color);self.key_path.setText(host.key_path);self.favorite.setChecked(host.favorite);self.auth.setCurrentIndex(1 if host.auth=="key" else 0)
            self.password.setPlaceholderText("Leave empty to keep the saved password")
            remove=PushButton(FIF.DELETE,"Delete this host",self);remove.clicked.connect(self._delete);self.viewLayout.addWidget(remove)
        self._update_color_button()
        self.auth.currentIndexChanged.connect(self._auth_changed);self.name.textChanged.connect(self._sync_valid);self.address.textChanged.connect(self._sync_valid);self.key_path.textChanged.connect(self._sync_valid);self._auth_changed(self.auth.currentIndex());self._sync_valid()
    def _browse(self):
        path,_=QFileDialog.getOpenFileName(self,"Select private key",str(Path.home()/".ssh"),"All files (*)")
        if path:self.key_path.setText(path)
    def _auth_changed(self,index):self.password.setEnabled(index==0);self.key_path.setEnabled(index==1);self.browse.setEnabled(index==1);self.passphrase.setEnabled(index==1);self._sync_valid()
    def _pick_color(self):
        value=QColorDialog.getColor(QColor(self.color.text()),self,"Choose host accent")
        if value.isValid():self.color.setText(value.name().upper());self._update_color_button()
    def _update_color_button(self):
        swatch=QPixmap(16,16);swatch.fill(QColor(self.color.text() if QColor(self.color.text()).isValid() else "#0A84FF"));self.color.setIcon(QIcon(swatch))
    def _sync_valid(self):self.yesButton.setEnabled(bool(self.name.text().strip() and self.address.text().strip() and (self.auth.currentIndex()==0 or self.key_path.text().strip())))
    def _delete(self):self.delete_requested=True;self.accept()
    def value(self):
        host=self.host or Host(name="",hostname="");host.name=self.name.text().strip();host.hostname=self.address.text().strip();host.username=self.user.text().strip() or "root";host.port=self.port.value();host.group=self.group.text().strip() or "Ungrouped";host.tags=[x.strip() for x in self.tags.text().replace(";",",").split(",") if x.strip()];host.color=self.color.text().strip() if QColor(self.color.text()).isValid() else "#0A84FF";host.auth="key" if self.auth.currentIndex() else "password";host.key_path=self.key_path.text().strip();host.favorite=self.favorite.isChecked();return host,self.password.text(),self.passphrase.text()


class GroupDialog(FluentForm):
    def __init__(self,parent=None,name:str=""):
        super().__init__(parent);self.begin("Rename group" if name else "New group",420)
        self.name=LineEdit(self);self.name.setPlaceholderText("Production, Games, Clients")
        self.form.addRow("Group name",self.name)
        if name:self.name.setText(name)
        self.name.textChanged.connect(self._sync_valid);self._sync_valid()
    def _sync_valid(self):self.yesButton.setEnabled(bool(self.name.text().strip()))
    def value(self):return self.name.text().strip()


class MoveGroupDialog(FluentForm):
    def __init__(self,host_name:str,groups:list[str],current:int=0,parent=None):
        super().__init__(parent);self.begin("Move host to group",420);self.yesButton.setText("Move")
        self.host=BodyLabel(host_name,self)
        self.group=ComboBox(self);self.group.addItems(groups)
        if groups:self.group.setCurrentIndex(max(0,min(current,len(groups)-1)))
        self.form.addRow("Host",self.host);self.form.addRow("Group",self.group)
    def value(self):return self.group.currentText()


class DeleteGroupDialog(MessageBoxBase):
    def __init__(self,group:str,count:int,parent=None):
        super().__init__(parent)
        self.titleLabel=SubtitleLabel("Delete group",self);self.viewLayout.addWidget(self.titleLabel)
        text=f"Delete \"{group}\"?"
        if count:text+=f"\n\n{count} host(s) will move to Ungrouped."
        else:text+="\n\nThe empty group will be removed."
        message=BodyLabel(text,self);message.setWordWrap(True);self.viewLayout.addWidget(message)
        self.widget.setMinimumWidth(420);self.yesButton.setText("Delete");self.cancelButton.setText("Cancel")


class SnippetDialog(FluentForm):
    def __init__(self,parent=None,snippet:Snippet|None=None):
        super().__init__(parent);self.snippet=snippet;self.begin("Command snippet",500);self.name=LineEdit(self);self.group=LineEdit(self);self.description=LineEdit(self);self.command=LineEdit(self);self.command.setPlaceholderText("docker ps --format '{{.Names}}'")
        if snippet:self.name.setText(snippet.name);self.group.setText(snippet.group);self.description.setText(snippet.description);self.command.setText(snippet.command)
        for label,widget in (("Name",self.name),("Group",self.group),("Description",self.description),("Command",self.command)):self.form.addRow(label,widget)
    def value(self):
        item=self.snippet or Snippet("","");item.name=self.name.text().strip() or "Untitled";item.group=self.group.text().strip() or "General";item.description=self.description.text().strip();item.command=self.command.text();return item


class TunnelDialog(FluentForm):
    def __init__(self,hosts:list[Host],parent=None,tunnel:TunnelRule|None=None):
        super().__init__(parent);self.hosts=hosts;self.tunnel=tunnel;self.begin("Edit TCP tunnel" if tunnel else "New TCP tunnel",540)
        self.name=LineEdit(self);self.name.setPlaceholderText("Minecraft, local website, database")
        self.host=ComboBox(self);self.host.addItems([h.name for h in hosts])
        self.bind_host=LineEdit(self);self.bind_host.setText("0.0.0.0");self.bind_host.setPlaceholderText("0.0.0.0")
        self.public_host=LineEdit(self);self.public_host.setPlaceholderText("Optional domain or public IP shown to users")
        self.remote_port=SpinBox(self);self.remote_port.setRange(1,65535);self.remote_port.setValue(25565)
        self.local_host=LineEdit(self);self.local_host.setText("127.0.0.1")
        self.local_port=SpinBox(self);self.local_port.setRange(1,65535);self.local_port.setValue(25565)
        self.persistent=CheckBox("Start automatically and keep running in tray",self)
        if tunnel:
            self.name.setText(tunnel.name);self.bind_host.setText(tunnel.bind_host);self.public_host.setText(tunnel.public_host);self.remote_port.setValue(tunnel.remote_port);self.local_host.setText(tunnel.local_host);self.local_port.setValue(tunnel.local_port);self.persistent.setChecked(tunnel.persistent)
            index=next((i for i,h in enumerate(hosts) if h.id==tunnel.host_id),0);self.host.setCurrentIndex(index)
        for label,widget in (("Name",self.name),("VPS host",self.host),("VPS bind address",self.bind_host),("Public host",self.public_host),("VPS TCP port",self.remote_port),("Local TCP address",self.local_host),("Local TCP port",self.local_port),("",self.persistent)):self.form.addRow(label,widget)
    def value(self):
        item=self.tunnel or TunnelRule("",self.hosts[self.host.currentIndex()].id,25565)
        item.name=self.name.text().strip() or "TCP tunnel";item.host_id=self.hosts[self.host.currentIndex()].id;item.bind_host=self.bind_host.text().strip() or "0.0.0.0";item.public_host=self.public_host.text().strip();item.remote_port=self.remote_port.value();item.local_host=self.local_host.text().strip() or "127.0.0.1";item.local_port=self.local_port.value();item.persistent=self.persistent.isChecked();return item
