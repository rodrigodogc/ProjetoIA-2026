"""python -m motorsim            -> interface gráfica
python -m motorsim --headless  -> sem interface (testes e scripts), ex.: --unbalance 0.5 --seconds 30
"""
import argparse
import ctypes
import time

from .engine import Engine, Params, Session


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://127.0.0.1:8765/ws/device", help="WebSocket do coletor")
    ap.add_argument("--connect", action="store_true", help="conecta ao coletor assim que abrir")
    ap.add_argument("--shot", help="(dev) salva uma captura da janela e fecha")
    ap.add_argument("--shot-after", type=float, default=6.0)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--seconds", type=float, default=0, help="headless: encerra após N s (0 = até Ctrl+C)")
    ap.add_argument("--seed", type=int, default=1, help="headless: semente da sessão (montagem do sensor)")
    ap.add_argument("--rpm", type=float, default=1800)
    ap.add_argument("--supply", choices=["inversor", "rede"], default="inversor")
    ap.add_argument("--load", type=float, default=0.5)
    ap.add_argument("--stopped", action="store_true", help="motor desligado")
    ap.add_argument("--drop", type=float, default=0.0, help="probabilidade de perder cada pacote")
    for k in ("unbalance", "misalignment", "looseness"):
        ap.add_argument("--" + k, type=float, default=0.0, help="severidade 0..1")
    a = ap.parse_args()

    if a.headless:
        from .link import Link, Runner
        p = Params(running=not a.stopped, supply=a.supply, rpm=a.rpm, load=a.load, unbalance=a.unbalance,
                   misalignment=a.misalignment, looseness=a.looseness)
        eng = Engine(Session(a.seed), p, seed=a.seed)
        link = Link()
        link.drop = a.drop
        link.connect(a.url)
        run = Runner(eng, link)
        run.start()
        print(f"headless: {a.url}  sessão {a.seed}  {eng.info()['rpm']:.0f} rpm  (Ctrl+C para parar)")
        t0 = time.time()
        try:
            while not a.seconds or time.time() - t0 < a.seconds:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        run.stop()
        link.disconnect()
        print(f"estado final: {link.state}, pacotes enviados: {link.sent}")
        return

    try:                                     # nítido em telas com escala > 100 %
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    from .gui import App
    App(a.url, auto_connect=a.connect, shot=a.shot, shot_after=a.shot_after).mainloop()


if __name__ == "__main__":
    main()
