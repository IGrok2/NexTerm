from __future__ import annotations

import re

import pyte
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPalette, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QApplication, QMessageBox, QPlainTextEdit, QVBoxLayout, QWidget

from .models import Host
from .ssh import SSHWorker
from .storage import Store


ANSI_COLORS = {
    "black":"#101216","red":"#f85149","green":"#3fb950","brown":"#d29922",
    "yellow":"#e3b341","blue":"#58a6ff","magenta":"#bc8cff","cyan":"#39c5cf",
    "white":"#d7dae0","brightblack":"#6e7681","brightred":"#ff7b72",
    "brightgreen":"#56d364","brightbrown":"#e3b341","brightyellow":"#f2cc60",
    "brightblue":"#79c0ff","brightmagenta":"#d2a8ff","brightcyan":"#56d4dd",
    "brightwhite":"#ffffff",
}


def terminal_color(name: str, fallback: QColor) -> QColor:
    if not name or name == "default": return fallback
    if name in ANSI_COLORS: return QColor(ANSI_COLORS[name])
    if len(name) == 6:
        value=QColor("#"+name)
        if value.isValid(): return value
    return fallback


class TerminalEdit(QPlainTextEdit):
    """Standard Qt text component backed by pyte; no custom painting."""
    dataToSend=pyqtSignal(str);terminalResized=pyqtSignal(int,int)
    KEY_MAP={
        Qt.Key_Up:"\x1b[A",Qt.Key_Down:"\x1b[B",Qt.Key_Right:"\x1b[C",Qt.Key_Left:"\x1b[D",
        Qt.Key_Home:"\x1b[H",Qt.Key_End:"\x1b[F",Qt.Key_PageUp:"\x1b[5~",Qt.Key_PageDown:"\x1b[6~",
        Qt.Key_Insert:"\x1b[2~",Qt.Key_Delete:"\x1b[3~",Qt.Key_Backspace:"\x7f",Qt.Key_Tab:"\t",
        Qt.Key_Escape:"\x1b",Qt.Key_Return:"\r",Qt.Key_Enter:"\r",
        Qt.Key_F1:"\x1bOP",Qt.Key_F2:"\x1bOQ",Qt.Key_F3:"\x1bOR",Qt.Key_F4:"\x1bOS",
        Qt.Key_F5:"\x1b[15~",Qt.Key_F6:"\x1b[17~",Qt.Key_F7:"\x1b[18~",Qt.Key_F8:"\x1b[19~",
        Qt.Key_F9:"\x1b[20~",Qt.Key_F10:"\x1b[21~",Qt.Key_F11:"\x1b[23~",Qt.Key_F12:"\x1b[24~",
    }
    def __init__(self,settings,parent=None):
        super().__init__(parent);self.settings=settings;self.cols=100;self.rows=30;self._render_pending=False;self._mouse_buttons=None;self._mouse_modes=set();self._last_frame=None
        self.screen=pyte.HistoryScreen(self.cols,self.rows,history=int(settings.get("scrollback",10000)),ratio=0.5);self.screen.set_mode(pyte.modes.LNM);self.stream=pyte.ByteStream(self.screen)
        self.setObjectName("terminalView");self.setUndoRedoEnabled(False);self.setLineWrapMode(QPlainTextEdit.NoWrap);self.setFocusPolicy(Qt.StrongFocus);self.setContextMenuPolicy(Qt.DefaultContextMenu);self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);self.document().setDocumentMargin(16);self.apply_settings(settings)
    def apply_settings(self,settings):
        self.settings=settings;size=max(12,int(settings.get("font_size",12)));font=QFont(settings.get("font","Cascadia Mono"),size)
        if not font.exactMatch():font=QFont("Consolas",size)
        font.setStyleHint(QFont.Monospace);self.setFont(font);palette=self.palette();palette.setColor(QPalette.Base,QColor(settings.get("terminal_bg","#0B0F14")));palette.setColor(QPalette.Text,QColor(settings.get("terminal_fg","#D7DEE8")));palette.setColor(QPalette.Highlight,QColor(settings.get("accent","#0A84FF")));palette.setColor(QPalette.HighlightedText,Qt.white);self.setPalette(palette);self.setCursorWidth(2);QApplication.setCursorFlashTime(1000 if settings.get("cursor_blink",True) else 0);self.update_size();self._last_frame=None;self.render_screen()
    def feed(self,data):
        if isinstance(data,str):data=data.encode("utf-8",errors="replace")
        self._update_mouse_modes(data)
        self.stream.feed(data)
        if not self._render_pending:
            self._render_pending=True;QTimer.singleShot(16,self.render_screen)
    def _update_mouse_modes(self,data:bytes):
        text=data.decode("ascii",errors="ignore")
        changed=False
        for match in re.finditer(r"\x1b\[\?([0-9;]+)([hl])",text):
            enabled=match.group(2)=="h"
            for mode in match.group(1).split(";"):
                if mode in {"1000","1002","1003","1006"}:
                    (self._mouse_modes.add if enabled else self._mouse_modes.discard)(mode);changed=True
        if changed:self.setMouseTracking(bool({"1002","1003"} & self._mouse_modes))
    def _mouse_reporting(self):return bool({"1000","1002","1003"} & self._mouse_modes)
    def _mouse_cell(self,event):
        fm=self.fontMetrics();margin=int(self.document().documentMargin())
        x=max(1,min(self.cols,(event.pos().x()-margin)//max(1,fm.horizontalAdvance("M"))+1))
        y=max(1,min(self.rows,(event.pos().y()-margin)//max(1,fm.height())+1))
        return x,y
    def _mouse_modifiers(self,event):
        mods=event.modifiers();value=0
        if mods&Qt.ShiftModifier:value|=4
        if mods&Qt.AltModifier:value|=8
        if mods&Qt.ControlModifier:value|=16
        return value
    def _send_mouse(self,code,x,y,release=False):
        if "1006" in self._mouse_modes:self.dataToSend.emit(f"\x1b[<{code};{x};{y}{'m' if release else 'M'}")
        else:self.dataToSend.emit("\x1b[M"+chr(min(255,32+code))+chr(min(255,32+x))+chr(min(255,32+y)))
    def status(self,text,color="36"):self.feed(f"\r\n\x1b[{color}m{text}\x1b[0m\r\n")
    def _format(self,char):
        fmt=QTextCharFormat();fg=terminal_color(char.fg,QColor(self.settings.get("terminal_fg","#D7E0EA")));bg=terminal_color(char.bg,QColor(self.settings.get("terminal_bg","#0F111A")))
        if char.reverse:fg,bg=bg,fg
        fmt.setForeground(fg);fmt.setBackground(bg);fmt.setFontWeight(QFont.Bold if char.bold else QFont.Normal);fmt.setFontItalic(bool(char.italics));fmt.setFontUnderline(bool(char.underscore));return fmt
    def render_screen(self):
        self._render_pending=False
        frame=[]
        for y in range(self.rows):
            line=self.screen.buffer[y]
            frame.append(tuple((line[x].data,line[x].fg,line[x].bg,line[x].bold,line[x].italics,line[x].underscore,line[x].reverse) for x in range(self.cols)))
        frame=(self.screen.cursor.x,self.screen.cursor.y,tuple(frame))
        if frame==self._last_frame:
            return
        self._last_frame=frame
        self.setUpdatesEnabled(False);old=self.textCursor();had_selection=old.hasSelection();cursor=QTextCursor(self.document());cursor.select(QTextCursor.Document);cursor.removeSelectedText()
        for y in range(self.rows):
            line=self.screen.buffer[y];run="";last=None
            for x in range(self.cols):
                char=line[x];key=(char.fg,char.bg,char.bold,char.italics,char.underscore,char.reverse)
                if last is not None and key!=last:cursor.insertText(run,self._format(previous));run=""
                run+=char.data or " ";last=key;previous=char
            if run:cursor.insertText(run.rstrip(),self._format(previous))
            if y<self.rows-1:cursor.insertBlock()
        if not had_selection:
            block=self.document().findBlockByNumber(min(self.rows-1,self.screen.cursor.y));pos=block.position()+min(self.screen.cursor.x,max(0,block.length()-1));cursor.setPosition(pos);self.setTextCursor(cursor)
        self.setUpdatesEnabled(True);self.viewport().update()
    def update_size(self):
        fm=self.fontMetrics();cols=max(20,(self.viewport().width()-36)//max(1,fm.horizontalAdvance("M")));rows=max(5,(self.viewport().height()-32)//max(1,fm.height()))
        if (cols,rows)!=(self.cols,self.rows):self.cols,self.rows=cols,rows;self.screen.resize(rows,cols);self._last_frame=None;self.terminalResized.emit(cols,rows)
    def resizeEvent(self,event):
        super().resizeEvent(event);old=(self.cols,self.rows);self.update_size()
        if old!=(self.cols,self.rows):self._last_frame=None;self.render_screen()
    def wheelEvent(self,event):
        if self._mouse_reporting():
            x,y=self._mouse_cell(event);self._send_mouse((64 if event.angleDelta().y()>0 else 65)+self._mouse_modifiers(event),x,y);return
        if event.modifiers()&Qt.ControlModifier:super().wheelEvent(event);return
        (self.screen.prev_page if event.angleDelta().y()>0 else self.screen.next_page)();self.render_screen()
    def keyPressEvent(self,event:QKeyEvent):
        key=event.key();mods=event.modifiers()
        if mods&Qt.ControlModifier and mods&Qt.ShiftModifier:
            if key==Qt.Key_C:self.copy();return
            if key==Qt.Key_V:self.dataToSend.emit(QApplication.clipboard().text().replace("\n","\r"));return
        if key in self.KEY_MAP:self.dataToSend.emit(self.KEY_MAP[key]);return
        if mods&Qt.ControlModifier:
            text=event.text()
            if len(text)==1 and text.isalpha():self.dataToSend.emit(chr(ord(text.upper())-64));return
        if event.text():self.dataToSend.emit(event.text())
    def mousePressEvent(self,event:QMouseEvent):
        if self._mouse_reporting():
            button={Qt.LeftButton:0,Qt.MiddleButton:1,Qt.RightButton:2}.get(event.button())
            if button is not None:
                self._mouse_buttons=button;x,y=self._mouse_cell(event);self._send_mouse(button+self._mouse_modifiers(event),x,y);return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event:QMouseEvent):
        if self._mouse_reporting() and ("1003" in self._mouse_modes or ("1002" in self._mouse_modes and self._mouse_buttons is not None)):
            x,y=self._mouse_cell(event);button=self._mouse_buttons if self._mouse_buttons is not None else 3;self._send_mouse(32+button+self._mouse_modifiers(event),x,y);return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event:QMouseEvent):
        if self._mouse_reporting():
            x,y=self._mouse_cell(event);self._send_mouse(3+self._mouse_modifiers(event),x,y,release=True);self._mouse_buttons=None;return
        super().mouseReleaseEvent(event)
        if self.settings.get("copy_on_select") and self.textCursor().hasSelection():
            self.copy()
    def paste_to_remote(self):
        text=QApplication.clipboard().text()
        if text:self.dataToSend.emit(text.replace("\r\n","\n").replace("\n","\r"))
    def clear_terminal(self):
        self.screen.reset();self._last_frame=None;self.render_screen()
    def zoom(self,delta:int):
        font=self.font();font.setPointSize(max(12,min(32,font.pointSize()+delta)));self.setFont(font);self.update_size();self._last_frame=None;self.render_screen()


class TerminalSession(QWidget):
    stateChanged=pyqtSignal(str,str)
    def __init__(self,host:Host,store:Store):
        super().__init__();self.host=host;self.store=store;self._closed=False;self._reconnect_attempts=0;self.status_message=f"Connecting to {host.name}...";self.view=TerminalEdit(store.data["settings"]);layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(self.view);self.worker=None;self.connect_ssh()
    def connect_ssh(self):
        if self._closed or (self.worker and self.worker.isRunning()):return
        self.view.status(f"NexTerm connecting to {self.host.username}@{self.host.hostname}:{self.host.port}","36");self.worker=SSHWorker(self.host,self.store.secret(self.host.id),self.store.secret(self.host.id,"passphrase"),int(self.store.data["settings"].get("keepalive",30)),str(self.store.known_hosts_path),self.store.private_key(self.host.id));self.worker.output.connect(self.view.feed);self.worker.state.connect(self._state);self.worker.hostKeyUnknown.connect(self._confirm_host_key);self.view.dataToSend.connect(self.worker.send);self.view.terminalResized.connect(self.worker.resize_pty);self.worker.start()
    def _confirm_host_key(self,hostname,fingerprint):
        accepted=QMessageBox.question(self,"Verify SSH host key",f"The identity of {hostname} has not been verified.\n\nFingerprint:\n{fingerprint}\n\nTrust and save this host key?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes
        if self.worker:self.worker.accept_host_key(accepted)
    def _state(self,state,message):
        self.status_message=message
        self.stateChanged.emit(state,message)
        if state=="connected":self._reconnect_attempts=0;self.view.status(f"Connected. Remote: {self.host.name} / {self.host.hostname}","32");self.store.add_history(self.host,"Connected")
        elif state=="error":self.view.status(f"Connection error: {message}","31");self.store.add_history(self.host,"Error",message)
        elif state=="disconnected":self.view.status(message,"33")
        if state in ("error","disconnected") and self.store.data["settings"].get("reconnect") and self._reconnect_attempts<3 and not self._closed:self._reconnect_attempts+=1;self.view.status(f"Reconnecting in 4 seconds ({self._reconnect_attempts}/3)...","33");QTimer.singleShot(4000,self.connect_ssh)
    def send_command(self,command):
        if self.worker:self.worker.send(command.rstrip("\r\n")+"\r")
    def reconnect(self):self.close_session();self._closed=False;self.connect_ssh()
    def close_session(self):
        self._closed=True
        if self.worker:self.worker.close();self.worker.wait(1500)
    def transport(self):return self.worker.client.get_transport() if self.worker and self.worker.client else None
    def client(self):
        if not self.worker or not self.worker.client:
            return None
        transport=self.worker.client.get_transport()
        return self.worker.client if transport and transport.is_active() else None
