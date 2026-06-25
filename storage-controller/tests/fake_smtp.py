"""A tiny in-process plain-SMTP server for tests (Python 3.14 removed smtpd).

Speaks just enough SMTP for smtplib: EHLO/AUTH/MAIL/RCPT/DATA/NOOP/QUIT. Records
received messages and can simulate rejection / temporary / permanent / auth
failures. No TLS — transport security modes are unit-tested separately.
"""

from __future__ import annotations

import socket
import threading


class FakeSMTP:
    def __init__(self, behavior: str = "ok", reject: list[str] | None = None) -> None:
        self.behavior = behavior  # ok | reject_all | reject_one | temp | perm | authfail
        self.reject = {a.lower() for a in (reject or [])}
        self.messages: list[tuple[str | None, list[str], bytes]] = []
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(5)
        self.port = self._srv.getsockname()[1]
        self._stop = False
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def _serve(self) -> None:
        self._srv.settimeout(0.3)
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except (TimeoutError, OSError):
                if self._stop:
                    break
                continue
            try:
                self._handle(conn)
            except OSError:
                pass
            finally:
                conn.close()

    def _handle(self, conn: socket.socket) -> None:
        rf = conn.makefile("rb")

        def send(s: str) -> None:
            conn.sendall((s + "\r\n").encode())

        send("220 fake ESMTP")
        mailfrom: str | None = None
        rcpts: list[str] = []
        while True:
            line = rf.readline()
            if not line:
                break
            cmd = line.decode(errors="replace").strip()
            up = cmd.upper()
            if up.startswith(("EHLO", "HELO")):
                send("250-fake.local")
                send("250 AUTH PLAIN LOGIN")
            elif up.startswith("AUTH"):
                send("535 5.7.8 Authentication failed" if self.behavior == "authfail" else "235 2.7.0 OK")
            elif up.startswith("MAIL FROM"):
                if self.behavior == "temp":
                    send("451 4.3.0 Temporary failure")
                elif self.behavior == "perm":
                    send("550 5.0.0 Permanent failure")
                else:
                    mailfrom = cmd
                    send("250 OK")
            elif up.startswith("RCPT TO"):
                addr = cmd.split(":", 1)[1].strip().strip("<>").lower() if ":" in cmd else ""
                if self.behavior == "reject_all" or addr in self.reject:
                    send("550 5.1.1 No such user")
                else:
                    rcpts.append(addr)
                    send("250 OK")
            elif up == "DATA":
                send("354 End data with <CR><LF>.<CR><LF>")
                data = b""
                while True:
                    dl = rf.readline()
                    if not dl or dl in (b".\r\n", b".\n"):
                        break
                    data += dl
                self.messages.append((mailfrom, list(rcpts), data))
                send("250 2.0.0 Queued")
                mailfrom, rcpts = None, []
            elif up == "NOOP":
                send("250 OK")
            elif up == "RSET":
                mailfrom, rcpts = None, []
                send("250 OK")
            elif up == "QUIT":
                send("221 Bye")
                break
            else:
                send("250 OK")

    def stop(self) -> None:
        self._stop = True
        try:
            self._srv.close()
        except OSError:
            pass
