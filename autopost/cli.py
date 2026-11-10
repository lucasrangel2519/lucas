"""Command line: python -m autopost <comando>."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from . import instagram, scheduler, tiktok
from .config import ROOT, Config

AGENDA_DIR = ROOT / "agenda"
STATE_FILE = AGENDA_DIR / "publicados.json"


def _extract_code(text: str) -> str:
    text = text.strip()
    if text.startswith("http"):
        code = parse_qs(urlparse(text).query).get("code", [""])[0]
        if not code:
            raise SystemExit("Nao achei '?code=' nesse link. Copie o endereco completo depois de autorizar.")
        return code
    return text


def _require(cfg: Config, *names: str) -> None:
    missing = [n for n in names if not getattr(cfg, n)]
    if missing:
        raise SystemExit("Faltam variaveis no .env: " + ", ".join(m.upper() for m in missing))


def _write_tokens(path: str | None, tokens: dict) -> None:
    if path and tokens:
        Path(path).write_text(json.dumps(tokens), encoding="utf-8")


# ----------------------------------------------------------------- commands
def cmd_auth_instagram(cfg: Config, args) -> None:
    _require(cfg, "ig_app_id", "ig_app_secret", "ig_redirect_uri")
    print("1) Abra este link, entre no Instagram @ da conta e clique em PERMITIR:\n")
    print("   " + instagram.authorize_url(cfg.ig_app_id, cfg.ig_redirect_uri) + "\n")
    print("2) Voce sera mandado para outra pagina. Copie o endereco COMPLETO da barra do navegador.")
    code = _extract_code(args.code or input("\nCole aqui o endereco (ou so o code): "))
    result = instagram.exchange_code(cfg.ig_app_id, cfg.ig_app_secret, cfg.ig_redirect_uri, code)
    print("\nPronto! Guarde estes valores no .env e nos Secrets do GitHub:\n")
    print(f"IG_USER_ID={result['user_id']}")
    print(f"IG_ACCESS_TOKEN={result['access_token']}")
    print("\n(O token vale ~60 dias; o GitHub Actions renova sozinho toda semana.)")


def cmd_auth_tiktok(cfg: Config, args) -> None:
    _require(cfg, "tiktok_client_key", "tiktok_client_secret", "tiktok_redirect_uri")
    print("1) Abra este link, entre no TikTok e clique em AUTORIZAR:\n")
    print("   " + tiktok.authorize_url(cfg.tiktok_client_key, cfg.tiktok_redirect_uri) + "\n")
    print("2) Voce sera mandado para outra pagina. Copie o endereco COMPLETO da barra do navegador.")
    code = _extract_code(args.code or input("\nCole aqui o endereco (ou so o code): "))
    result = tiktok.exchange_code(cfg.tiktok_client_key, cfg.tiktok_client_secret, cfg.tiktok_redirect_uri, code)
    print("\nPronto! Guarde este valor no .env e nos Secrets do GitHub:\n")
    print(f"TIKTOK_REFRESH_TOKEN={result['refresh_token']}")
    print("\n(Vale 1 ano; cada uso renova.)")


def _tiktok_access(cfg: Config, tokens: dict) -> str:
    if cfg.tiktok_access_token:
        return cfg.tiktok_access_token
    _require(cfg, "tiktok_client_key", "tiktok_client_secret", "tiktok_refresh_token")
    data = tiktok.refresh_token(cfg.tiktok_client_key, cfg.tiktok_client_secret, cfg.tiktok_refresh_token)
    cfg.tiktok_access_token = data["access_token"]
    if data.get("refresh_token") and data["refresh_token"] != cfg.tiktok_refresh_token:
        tokens["TIKTOK_REFRESH_TOKEN"] = data["refresh_token"]
        cfg.tiktok_refresh_token = data["refresh_token"]
    return cfg.tiktok_access_token


def make_publisher(cfg: Config, tokens: dict):
    clients: dict = {}

    def ig() -> instagram.InstagramClient:
        if "ig" not in clients:
            clients["ig"] = instagram.InstagramClient(
                cfg.ig_user_id, cfg.ig_access_token, cfg.ig_api_version, cfg.media_base_url, ROOT
            )
        return clients["ig"]

    def tt() -> tiktok.TikTokClient:
        if "tt" not in clients:
            clients["tt"] = tiktok.TikTokClient(
                _tiktok_access(cfg, tokens), cfg.tiktok_privacy_level, cfg.tiktok_brand_organic, ROOT
            )
        return clients["tt"]

    def publish(item: scheduler.Item) -> str:
        if cfg.dry_run:
            return "dry-run"
        if item.platform == "tiktok":
            return tt().post_video(item.files[0], item.caption, item.brand_organic)
        client = ig()
        if item.kind == "post":
            return client.post(item.files[0], item.caption)
        if item.kind == "carrossel":
            return client.carousel(item.files, item.caption)
        if item.kind == "reels":
            return client.reel(item.files[0], item.caption)
        return client.story(item.files[0])

    return publish


def _files_present(item: scheduler.Item) -> bool:
    return all(ref.startswith("http") or (ROOT / ref).exists() for ref in item.files)


def cmd_run(cfg: Config, args) -> None:
    tz = ZoneInfo(cfg.timezone)
    items = scheduler.load_agenda(AGENDA_DIR, tz)
    state = scheduler.State.load(STATE_FILE)
    now = datetime.now(tz)
    tokens: dict = {}
    due = scheduler.due_items(items, state, now, timedelta(hours=cfg.late_window_hours))
    print(f"{now:%Y-%m-%d %H:%M} - {len(items)} itens na agenda, {len(due)} para publicar agora.")
    try:
        failures = scheduler.run(
            items,
            state,
            make_publisher(cfg, tokens),
            now,
            timedelta(hours=cfg.late_window_hours),
            is_ready=_files_present,
        )
    finally:
        _write_tokens(args.tokens_out, tokens)
    if failures:
        sys.exit(1)


def cmd_refresh(cfg: Config, args) -> None:
    tokens: dict = {}
    # tokens EAA (usuario do sistema) nao expiram: so renova tokens IG
    if cfg.ig_access_token and not cfg.ig_access_token.startswith("EAA"):
        data = instagram.refresh_token(cfg.ig_access_token)
        tokens["IG_ACCESS_TOKEN"] = data["access_token"]
        print(f"Instagram: token renovado (expira em {int(data.get('expires_in', 0)) // 86400} dias)")
    if cfg.tiktok_refresh_token:
        _tiktok_access(cfg, tokens)
        print("TikTok: token renovado")
    _write_tokens(args.tokens_out, tokens)


def cmd_check(cfg: Config, args) -> None:
    tz = ZoneInfo(cfg.timezone)
    items = scheduler.load_agenda(AGENDA_DIR, tz)
    state = scheduler.State.load(STATE_FILE)
    problems = 0
    now = datetime.now(tz)
    for item in items:
        if item.id in state.published or item.when < now - timedelta(hours=cfg.late_window_hours):
            continue
        for ref in item.files:
            if not ref.startswith("http") and not (ROOT / ref).exists():
                problems += 1
                print(f"  arquivo faltando: {ref}  ({item.id}, {item.when:%d/%m %H:%M})")
    pending = [i for i in items if i.id not in state.published]
    print(f"Agenda OK: {len(items)} itens ({len(pending)} pendentes). Arquivos faltando: {problems}.")
    if args.strict and problems:
        sys.exit(1)


def cmd_test(cfg: Config, args) -> None:
    tokens: dict = {}
    if cfg.ig_access_token:
        client = instagram.InstagramClient(cfg.ig_user_id, cfg.ig_access_token, cfg.ig_api_version)
        print("Instagram conectado. Limite de postagens:", client.publishing_limit())
    else:
        print("Instagram: sem IG_ACCESS_TOKEN")
    if cfg.tiktok_refresh_token or cfg.tiktok_access_token:
        info = tiktok.TikTokClient(_tiktok_access(cfg, tokens)).creator_info()
        print(f"TikTok conectado: @{info.get('creator_username')} | privacidade permitida: {info.get('privacy_level_options')}")
    else:
        print("TikTok: sem TIKTOK_REFRESH_TOKEN")
    _write_tokens(args.tokens_out, tokens)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="autopost", description="Postagem automatica no TikTok e Instagram")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in [
        ("auth-instagram", cmd_auth_instagram, "conectar a conta do Instagram (uma vez)"),
        ("auth-tiktok", cmd_auth_tiktok, "conectar a conta do TikTok (uma vez)"),
    ]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--code", help="codigo ou link de retorno (senao pergunta)")
        p.set_defaults(fn=fn)
    for name, fn, help_ in [
        ("run", cmd_run, "publicar o que esta na hora"),
        ("refresh-tokens", cmd_refresh, "renovar tokens"),
        ("testar", cmd_test, "testar as conexoes"),
    ]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--tokens-out", help="arquivo JSON para salvar tokens renovados")
        p.set_defaults(fn=fn)
    p = sub.add_parser("validar", help="checar a agenda e os arquivos")
    p.add_argument("--strict", action="store_true", help="falhar se faltar arquivo")
    p.set_defaults(fn=cmd_check)

    args = parser.parse_args(argv)
    try:
        args.fn(Config.from_env(), args)
    except (scheduler.AgendaError, instagram.InstagramError, tiktok.TikTokError) as exc:
        raise SystemExit(f"Erro: {exc}")
