from __future__ import annotations

import select
import socket
import threading
import time
import base64
import hashlib
import struct
from io import StringIO

import paramiko
from PyQt5.QtCore import QThread, pyqtSignal

from .models import Host, TunnelRule


def load_private_key(value:str,passphrase:str=""):
    errors=[]
    key_types=[paramiko.Ed25519Key,paramiko.ECDSAKey,paramiko.RSAKey]
    if hasattr(paramiko,"DSSKey"):key_types.append(paramiko.DSSKey)
    for key_type in key_types:
        try:return key_type.from_private_key(StringIO(value),password=passphrase or None)
        except (paramiko.SSHException,ValueError) as exc:errors.append(exc)
    raise paramiko.SSHException(str(errors[-1]) if errors else "Unsupported private key")


class ConfirmHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, worker): self.worker = worker
    def missing_host_key(self, client, hostname, key):
        digest=base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        self.worker._host_decision.clear();self.worker._host_accepted=False
        self.worker.hostKeyUnknown.emit(hostname,f"SHA256:{digest}")
        if not self.worker._host_decision.wait(60) or not self.worker._host_accepted: raise paramiko.SSHException("Host key was not trusted")
        client._host_keys.add(hostname,key.get_name(),key)
        if client._host_keys_filename: client.save_host_keys(client._host_keys_filename)


class SSHWorker(QThread):
    output = pyqtSignal(bytes)
    state = pyqtSignal(str, str)
    hostKeyUnknown = pyqtSignal(str, str)

    def __init__(self, host: Host, password: str = "", passphrase: str = "", keepalive: int = 30, known_hosts_path: str = "", private_key: str = ""):
        super().__init__()
        self.host = host
        self.password = password
        self.passphrase = passphrase
        self.keepalive = keepalive
        self.known_hosts_path = known_hosts_path
        self.private_key = private_key
        self.client: paramiko.SSHClient | None = None
        self.channel: paramiko.Channel | None = None
        self._stopping = False
        self._send_lock = threading.Lock()
        self._host_decision = threading.Event(); self._host_accepted = False

    def run(self):
        try:
            self.state.emit("connecting", f"Connecting to {self.host.hostname}…")
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if self.known_hosts_path:
                client.load_host_keys(self.known_hosts_path)
            client.set_missing_host_key_policy(ConfirmHostKeyPolicy(self))
            kwargs = dict(
                hostname=self.host.hostname, port=self.host.port, username=self.host.username,
                timeout=15, banner_timeout=15, auth_timeout=15, allow_agent=True, look_for_keys=True,
            )
            if self.host.auth == "key":
                if self.private_key:kwargs.update(pkey=load_private_key(self.private_key,self.passphrase))
                elif self.host.key_path:kwargs.update(key_filename=self.host.key_path, passphrase=self.passphrase or None)
            else:
                kwargs.update(password=self.password or None)
            client.connect(**kwargs)
            transport = client.get_transport()
            if transport:
                transport.set_keepalive(self.keepalive)
            self.client = client
            self.channel = client.invoke_shell(term="xterm-256color", width=150, height=40)
            self.channel.settimeout(0.15)
            self.state.emit("connected", f"Connected to {self.host.name}")
            while not self._stopping and self.channel and not self.channel.closed:
                try:
                    if self.channel.recv_ready():
                        chunk = self.channel.recv(65535)
                        if not chunk:
                            break
                        self.output.emit(chunk)
                    else:
                        time.sleep(0.02)
                except socket.timeout:
                    continue
            if not self._stopping:
                self.state.emit("disconnected", "Remote host closed the connection")
        except Exception as exc:
            self.state.emit("error", str(exc) or exc.__class__.__name__)
        finally:
            self.close()

    def send(self, value: str):
        try:
            with self._send_lock:
                if self.channel and not self.channel.closed:
                    self.channel.send(value)
        except Exception as exc:
            self.state.emit("error", str(exc))

    def accept_host_key(self, accepted: bool):
        self._host_accepted = accepted; self._host_decision.set()

    def resize_pty(self, columns: int, rows: int):
        try:
            if self.channel and not self.channel.closed:
                self.channel.resize_pty(max(20, columns), max(5, rows))
        except Exception:
            pass

    def close(self):
        self._stopping = True
        self._host_decision.set()
        try:
            if self.channel:
                self.channel.close()
            if self.client:
                self.client.close()
        except Exception:
            pass
        finally:
            self.channel = None
            self.client = None


class ReverseTunnelServer(QThread):
    status = pyqtSignal(str, str)

    def __init__(self, host: Host, rule: TunnelRule, password: str = "", passphrase: str = "", keepalive: int = 30, known_hosts_path: str = "", private_key: str = ""):
        super().__init__()
        self.host = host
        self.rule = rule
        self.password = password
        self.passphrase = passphrase
        self.keepalive = keepalive
        self.known_hosts_path = known_hosts_path
        self.private_key = private_key
        self.client: paramiko.SSHClient | None = None
        self.transport: paramiko.Transport | None = None
        self.channel: paramiko.Channel | None = None
        self._stopping = threading.Event()
        self._send_lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        self._local_sockets: dict[int, socket.socket] = {}

    def run(self):
        try:
            self.status.emit("connecting", f"Opening tunnel on {self.host.hostname}:{self.rule.remote_port}")
            try:
                probe = socket.create_connection((self.rule.local_host, self.rule.local_port), timeout=3)
                probe.close()
            except OSError as exc:
                raise ConnectionError(f"Local target {self.rule.local_host}:{self.rule.local_port} is not reachable. Start the local app/server or fix the local port. {exc}")
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if self.known_hosts_path:
                client.load_host_keys(self.known_hosts_path)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            kwargs = dict(
                hostname=self.host.hostname, port=self.host.port, username=self.host.username,
                timeout=15, banner_timeout=15, auth_timeout=15, allow_agent=True, look_for_keys=True,
            )
            if self.host.auth == "key":
                if self.private_key:
                    kwargs.update(pkey=load_private_key(self.private_key,self.passphrase))
                elif self.host.key_path:
                    kwargs.update(key_filename=self.host.key_path, passphrase=self.passphrase or None)
            else:
                kwargs.update(password=self.password or None)
            client.connect(**kwargs)
            transport = client.get_transport()
            if not transport:
                raise paramiko.SSHException("SSH transport is not available")
            transport.set_keepalive(self.keepalive)
            self.client = client
            self.transport = transport
            self.channel = self._start_remote_relay(transport)
            self._relay_loop(self.channel)
            if not self._stopping.is_set():
                self.status.emit("stopped", "SSH transport closed")
        except Exception as exc:
            self.status.emit("error", str(exc) or exc.__class__.__name__)
        finally:
            self.stop()

    def _start_remote_relay(self, transport: paramiko.Transport) -> paramiko.Channel:
        script = self._remote_relay_script()
        encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
        last_error = ""
        for python in ("python3", "python"):
            channel = transport.open_session()
            channel.set_combine_stderr(False)
            channel.settimeout(1)
            command = f"{python} -u -c \"import base64;exec(base64.b64decode('{encoded}'))\""
            channel.exec_command(command)
            try:
                frame_type, _, payload = self._read_frame(channel, timeout=5)
                if frame_type == b"S":
                    detail = payload.decode("utf-8", "replace")
                    self.status.emit("running", detail)
                    return channel
                if frame_type == b"E":
                    last_error = payload.decode("utf-8", "replace")
            except Exception as exc:
                stderr = b""
                try:
                    if channel.recv_stderr_ready():
                        stderr = channel.recv_stderr(4096)
                except Exception:
                    pass
                last_error = (stderr.decode("utf-8", "replace").strip() or str(exc))
            try:
                channel.close()
            except Exception:
                pass
        raise RuntimeError(last_error or "Could not start remote TCP relay. Install python3 on the VPS.")

    def _relay_loop(self, channel: paramiko.Channel):
        while not self._stopping.is_set() and not channel.closed:
            try:
                frame_type, conn_id, payload = self._read_frame(channel, timeout=1)
            except TimeoutError:
                continue
            if frame_type == b"O":
                self._open_local(conn_id)
            elif frame_type == b"D":
                sock = self._local_sockets.get(conn_id)
                if sock:
                    try:sock.sendall(payload)
                    except OSError:self._close_local(conn_id, notify_remote=True)
            elif frame_type == b"C":
                self._close_local(conn_id, notify_remote=False)
            elif frame_type in (b"E", b"W"):
                self.status.emit("warning" if frame_type == b"W" else "error", payload.decode("utf-8", "replace"))
                if frame_type == b"E":
                    break

    def _open_local(self, conn_id: int):
        try:
            sock = socket.create_connection((self.rule.local_host, self.rule.local_port), timeout=10)
            self._local_sockets[conn_id] = sock
            thread = threading.Thread(target=self._pump_local_to_remote, args=(conn_id,sock), daemon=True)
            thread.start()
            self._workers.append(thread)
        except OSError as exc:
            self.status.emit("warning", f"Incoming tunnel connection could not reach local target {self.rule.local_host}:{self.rule.local_port}: {exc}")
            self._send_frame(b"C", conn_id, b"")

    def _pump_local_to_remote(self, conn_id: int, sock: socket.socket):
        try:
            while not self._stopping.is_set():
                data = sock.recv(16384)
                if not data:
                    break
                self._send_frame(b"D", conn_id, data)
        except OSError:
            pass
        finally:
            self._close_local(conn_id, notify_remote=True)

    def _close_local(self, conn_id: int, notify_remote: bool):
        sock = self._local_sockets.pop(conn_id, None)
        if sock:
            try:sock.close()
            except OSError:pass
        if notify_remote and self.channel and not self.channel.closed:
            self._send_frame(b"C", conn_id, b"")

    def _send_frame(self, frame_type: bytes, conn_id: int, payload: bytes):
        if not self.channel or self.channel.closed:
            return
        with self._send_lock:
            self.channel.sendall(struct.pack(">cII", frame_type, conn_id, len(payload)) + payload)

    def _read_frame(self, channel: paramiko.Channel, timeout: float = 1):
        header = self._recv_exact(channel, 9, timeout)
        frame_type, conn_id, size = struct.unpack(">cII", header)
        payload = self._recv_exact(channel, size, timeout) if size else b""
        return frame_type, conn_id, payload

    def _recv_exact(self, channel: paramiko.Channel, size: int, timeout: float):
        deadline = time.time() + timeout
        chunks = []
        remaining = size
        while remaining:
            if self._stopping.is_set():
                raise EOFError("Tunnel stopped")
            if time.time() > deadline:
                raise TimeoutError()
            try:
                chunk = channel.recv(remaining)
            except socket.timeout:
                continue
            if not chunk:
                raise EOFError("Remote relay closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _remote_relay_script(self) -> str:
        return f'''
import socket, select, struct, sys, threading

BIND_HOST = {self.rule.bind_host!r}
PUBLIC_HOST = {self.rule.public_host or self.host.hostname!r}
REMOTE_PORT = {int(self.rule.remote_port)!r}
TARGET = {self.rule.local_host!r} + ":" + str({int(self.rule.local_port)!r})
conns = {{}}
next_id = 1
lock = threading.Lock()
write_lock = threading.Lock()
stopping = False

def send_frame(kind, conn_id, data=b""):
    if isinstance(kind, str):
        kind = kind.encode("ascii")
    with write_lock:
        sys.stdout.buffer.write(struct.pack(">cII", kind, conn_id, len(data)) + data)
        sys.stdout.buffer.flush()

def close_conn(conn_id, notify=True):
    sock = None
    with lock:
        sock = conns.pop(conn_id, None)
    if sock:
        try:
            sock.close()
        except OSError:
            pass
    if notify:
        send_frame("C", conn_id)

def stdin_loop():
    global stopping
    try:
        while True:
            header = sys.stdin.buffer.read(9)
            if len(header) != 9:
                break
            kind, conn_id, size = struct.unpack(">cII", header)
            payload = sys.stdin.buffer.read(size) if size else b""
            if kind == b"D":
                with lock:
                    sock = conns.get(conn_id)
                if sock:
                    try:
                        sock.sendall(payload)
                    except OSError:
                        close_conn(conn_id)
            elif kind == b"C":
                close_conn(conn_id, notify=False)
    finally:
        stopping = True
        with lock:
            ids = list(conns)
        for conn_id in ids:
            close_conn(conn_id, notify=False)

try:
    server = socket.socket(socket.AF_INET6 if ":" in BIND_HOST else socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((BIND_HOST, REMOTE_PORT))
    server.listen(128)
    server.setblocking(False)
except Exception as exc:
    send_frame("E", 0, ("Could not listen on %s:%s: %s" % (BIND_HOST, REMOTE_PORT, exc)).encode())
    raise SystemExit(1)

send_frame("S", 0, ("%s:%s -> %s via NexTerm relay. Open the VPS firewall for this TCP port if needed." % (PUBLIC_HOST, REMOTE_PORT, TARGET)).encode())
threading.Thread(target=stdin_loop, daemon=True).start()

while not stopping:
    with lock:
        sockets = list(conns.values())
        reverse = {{sock: cid for cid, sock in conns.items()}}
    try:
        readable, _, _ = select.select([server] + sockets, [], [], 1)
    except OSError:
        continue
    for sock in readable:
        if sock is server:
            try:
                client, _ = server.accept()
                client.setblocking(False)
            except OSError:
                continue
            with lock:
                conn_id = next_id
                next_id += 1
                conns[conn_id] = client
            send_frame("O", conn_id)
        else:
            conn_id = reverse.get(sock)
            if conn_id is None:
                continue
            try:
                data = sock.recv(16384)
            except OSError:
                data = b""
            if data:
                send_frame("D", conn_id, data)
            else:
                close_conn(conn_id)
'''

    def stop(self):
        self._stopping.set()
        for conn_id in list(self._local_sockets):
            self._close_local(conn_id, notify_remote=False)
        try:
            if self.channel:
                self.channel.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
