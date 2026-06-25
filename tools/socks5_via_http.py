"""Tiny SOCKS5 server that tunnels through an upstream HTTP CONNECT proxy.

For TESTING ONLY — lets us exercise the app's socks5 support using an
HTTP-only upstream (e.g. a gluetun/NordVPN container).

    python tools/socks5_via_http.py 11080 127.0.0.1 18888
    # now socks5://127.0.0.1:11080 exits through http://127.0.0.1:18888
"""
import asyncio
import socket
import struct
import sys

UP_HOST = "127.0.0.1"
UP_PORT = 18888


async def _pipe(r, w):
    try:
        while True:
            data = await r.read(65536)
            if not data:
                break
            w.write(data)
            await w.drain()
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def handle(creader, cwriter):
    try:
        # greeting
        ver, n = struct.unpack("!BB", await creader.readexactly(2))
        await creader.readexactly(n)
        cwriter.write(b"\x05\x00")
        await cwriter.drain()
        # request
        ver, cmd, rsv, atyp = struct.unpack("!BBBB", await creader.readexactly(4))
        if atyp == 1:
            host = socket.inet_ntoa(await creader.readexactly(4))
        elif atyp == 3:
            ln = (await creader.readexactly(1))[0]
            host = (await creader.readexactly(ln)).decode()
        elif atyp == 4:
            host = socket.inet_ntop(socket.AF_INET6, await creader.readexactly(16))
        else:
            cwriter.close(); return
        port = struct.unpack("!H", await creader.readexactly(2))[0]
        if cmd != 1:
            cwriter.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00"); await cwriter.drain(); cwriter.close(); return
        # open upstream HTTP CONNECT tunnel
        ureader, uwriter = await asyncio.open_connection(UP_HOST, UP_PORT)
        uwriter.write(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        await uwriter.drain()
        line = await ureader.readline()
        if b"200" not in line:
            cwriter.write(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00"); await cwriter.drain(); cwriter.close(); return
        while True:
            h = await ureader.readline()
            if h in (b"\r\n", b"\n", b""):
                break
        cwriter.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await cwriter.drain()
        await asyncio.gather(_pipe(creader, uwriter), _pipe(ureader, cwriter))
    except Exception:
        try:
            cwriter.close()
        except Exception:
            pass


async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 11080
    global UP_HOST, UP_PORT
    if len(sys.argv) > 2:
        UP_HOST = sys.argv[2]
    if len(sys.argv) > 3:
        UP_PORT = int(sys.argv[3])
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    print(f"socks5 on 127.0.0.1:{port} -> http {UP_HOST}:{UP_PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
