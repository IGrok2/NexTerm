from __future__ import annotations

import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal


class DiscordRpc(QObject):
    statusChanged=pyqtSignal(bool,str)

    def __init__(self,parent=None):
        super().__init__(parent);self._stop=threading.Event();self._thread=None;self._rpc=None

    def configure(self,enabled:bool,client_id:str,details:str):
        self.stop()
        if not enabled:return
        if not client_id.isdigit():self.statusChanged.emit(False,"Discord Application ID is required");return
        self._stop.clear();self._thread=threading.Thread(target=self._run,args=(client_id,details),daemon=True,name="DiscordRPC");self._thread.start()

    def _run(self,client_id:str,details:str):
        try:
            from pypresence import Presence
            rpc=Presence(client_id);self._rpc=rpc;rpc.connect();rpc.update(details=(details or "Using NexTerm")[:128],state="SSH workspace",start=int(time.time()));self.statusChanged.emit(True,"Discord Rich Presence connected")
            self._stop.wait()
        except Exception as exc:self.statusChanged.emit(False,f"Discord RPC: {exc}")
        finally:
            rpc=self._rpc;self._rpc=None
            if rpc:
                try:rpc.clear();rpc.close()
                except Exception:pass

    def stop(self):
        self._stop.set();rpc=self._rpc
        if rpc:
            try:rpc.close()
            except Exception:pass
        thread=self._thread
        if thread and thread.is_alive():thread.join(timeout=1)
        self._thread=None
