"""frontdoor-admin CLI — management interface for frontdoor.

Wraps the frontdoor Management API for local and remote use. Designed
for both human operators and AI agents — use --help for rich skill-format
help, -h for traditional short help.
"""

import json
import os
import sys
from pathlib import Path

import click
import httpx


# ---------------------------------------------------------------------------
# Rich help text
# ---------------------------------------------------------------------------

RICH_HELP_TOP = """\
WHAT THIS TOOL DOES
  Manages frontdoor-integrated services on one or more hosts via the frontdoor
  Management API. Handles app registration, service control, port allocation,
  manifest management, and API token administration.

WHEN TO USE THIS TOOL
  Use frontdoor-admin when you need to:
  - Register a new web app with frontdoor (Caddy vhost + systemd unit + manifest)
  - Install a pre-built known-app config (muxplex, filebrowser, etc.)
  - Allocate free ports before starting a new app provisioning workflow
  - Restart services or perform fleet-wide restarts
  - Manage API tokens for remote access across Tailscale fleet

WORKFLOW
  Typical app registration:
    1. frontdoor-admin ports next          # find free ports
    2. frontdoor-admin app register ...    # register the app
    3. frontdoor-admin services list       # verify it's running

  For pre-built apps:
    1. frontdoor-admin known-apps list     # check what's available
    2. frontdoor-admin known-apps install APPNAME --service-user USER

  Remote management:
    1. frontdoor-admin token create --name "my-laptop"  # on the target box
    2. frontdoor-admin box add mybox --url https://mybox.ts.net --token ft_...
    3. frontdoor-admin --box mybox services list

AUTHENTICATION
  Local (same machine): no token required — localhost bypass applies.
  Remote: set FRONTDOOR_TOKEN=ft_... or configure ~/.config/frontdoor/cli.toml.

COMMANDS
  ports         Port allocation
  manifest      Manifest management (list, set, delete)
  services      Service control (list, restart, restart-all)
  app           App registration (register, unregister)
  known-apps    Pre-built app configs (list, install)
  token         API token management (create, list, revoke)
  box           Fleet box aliases (add, list, remove)

SEE ALSO
  frontdoor-admin <command> --help    Rich help for any subcommand
  frontdoor-admin <command> -h        Short help for any subcommand
"""

SHORT_HELP_TOP = """\
frontdoor-admin — frontdoor management CLI

Commands: ports, manifest, services, app, known-apps, token, box
Options:  --box NAME, --url URL, --token TOKEN

Use --help for detailed agent-readable help.
"""


# ---------------------------------------------------------------------------
# Box config
# ---------------------------------------------------------------------------


def _load_box_config() -> dict:
    """Load ~/.config/frontdoor/cli.toml if it exists."""
    config_path = Path.home() / ".config" / "frontdoor" / "cli.toml"
    if not config_path.exists():
        return {}
    try:
        import tomllib

        return tomllib.loads(config_path.read_text())
    except ImportError:
        return {}
    except Exception:
        return {}


def _resolve_target(ctx: click.Context) -> tuple[str, str | None]:
    """Resolve URL and token from CLI flags, env, or config.

    Resolution order:
    1. --box flag → config lookup
    2. --url + --token flags
    3. FRONTDOOR_BOX / FRONTDOOR_URL / FRONTDOOR_TOKEN env vars
    4. Config file defaults
    5. http://localhost:8420 (hardcoded fallback)
    """
    params = ctx.obj or {}
    box_name = params.get("box")
    url = params.get("url")
    token = params.get("token")

    config = _load_box_config()

    if box_name:
        boxes = config.get("boxes", {})
        if box_name in boxes:
            box = boxes[box_name]
            return box.get("url", "http://localhost:8420"), box.get("token")
        click.echo(f"Error: box '{box_name}' not found in config", err=True)
        sys.exit(1)

    if url:
        return url, token

    env_box = os.environ.get("FRONTDOOR_BOX")
    if env_box:
        boxes = config.get("boxes", {})
        if env_box in boxes:
            box = boxes[env_box]
            return box.get("url", "http://localhost:8420"), box.get("token")

    env_url = os.environ.get("FRONTDOOR_URL")
    if env_url:
        return env_url, os.environ.get("FRONTDOOR_TOKEN")

    defaults = config.get("defaults", {})
    default_box = defaults.get("box")
    if default_box:
        boxes = config.get("boxes", {})
        if default_box in boxes:
            box = boxes[default_box]
            return box.get("url", "http://localhost:8420"), box.get("token")

    return "http://localhost:8420", None


def _api_request(
    ctx: click.Context,
    method: str,
    path: str,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    """Make an authenticated API request to the target frontdoor instance."""
    url, token = _resolve_target(ctx)
    full_url = f"{url.rstrip('/')}/api/admin{path}"

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.request(
            method,
            full_url,
            json=json_body,
            params=params,
            headers=headers,
            timeout=30,
        )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError):
        click.echo(f"Error: could not connect to {url}", err=True)
        sys.exit(1)

    if resp.status_code >= 400:
        try:
            error = resp.json()
            detail = error.get("detail", {})
            if isinstance(detail, dict):
                msg = detail.get("error", resp.text)
            else:
                msg = str(detail)
            click.echo(f"Error ({resp.status_code}): {msg}", err=True)
        except Exception:
            click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    return resp.json()


# ---------------------------------------------------------------------------
# Short help callback
# ---------------------------------------------------------------------------


def _short_help_callback(
    ctx: click.Context, param: click.Parameter, value: bool
) -> None:
    if not value:
        return
    if ctx.parent is None:
        click.echo(SHORT_HELP_TOP)
    else:
        cmd = ctx.command
        click.echo(f"{cmd.name} — {cmd.help or ''}")
        click.echo()
        for p in cmd.params:
            if isinstance(p, click.Option) and p.name not in ("short_help",):
                opts = ", ".join(p.opts)
                click.echo(f"  {opts:30s} {p.help or ''}")
        for p in cmd.params:
            if isinstance(p, click.Argument):
                click.echo(f"  {p.name:30s} argument")
    ctx.exit()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


class RichHelpGroup(click.Group):
    """Click group with custom --help that shows rich skill-format text."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write(RICH_HELP_TOP)


@click.group(cls=RichHelpGroup, context_settings=dict(help_option_names=["--help"]))
@click.option("--box", default=None, help="Named box alias from config")
@click.option("--url", default=None, help="Direct URL to frontdoor instance")
@click.option("--token", default=None, help="API token for remote auth")
@click.option(
    "-h",
    "short_help",
    is_flag=True,
    callback=_short_help_callback,
    expose_value=False,
    is_eager=True,
    help="Short help",
)
@click.pass_context
def main(
    ctx: click.Context, box: str | None, url: str | None, token: str | None
) -> None:
    """frontdoor-admin — frontdoor management CLI"""
    ctx.ensure_object(dict)
    ctx.obj["box"] = box
    ctx.obj["url"] = url
    ctx.obj["token"] = token


# ---------------------------------------------------------------------------
# ports
# ---------------------------------------------------------------------------


@main.group()
def ports() -> None:
    """Port allocation commands."""


@ports.command("next")
@click.option("--start", default=8440, type=int, help="Start scanning from this port")
@click.option(
    "--show-used", is_flag=True, help="Also show all ports frontdoor considers taken"
)
@click.pass_context
def ports_next(ctx: click.Context, start: int, show_used: bool) -> None:
    """Get the next available internal + external port pair."""
    params: dict = {"start": start}
    if show_used:
        params["show_used"] = "true"
    result = _api_request(ctx, "GET", "/ports/next", params=params)
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


@main.group()
def manifest() -> None:
    """Manifest management commands."""


@manifest.command("list")
@click.pass_context
def manifest_list(ctx: click.Context) -> None:
    """List all installed manifests."""
    result = _api_request(ctx, "GET", "/manifests")
    click.echo(json.dumps(result, indent=2))


@manifest.command("set")
@click.argument("slug")
@click.option("--name", required=True, help="Human-readable name")
@click.option("--desc", "--description", default="", help="One-line description")
@click.option("--icon", default="", help="Emoji or Phosphor icon keyword")
@click.pass_context
def manifest_set(
    ctx: click.Context, slug: str, name: str, desc: str, icon: str
) -> None:
    """Create or update a manifest."""
    result = _api_request(
        ctx,
        "PUT",
        f"/manifests/{slug}",
        json_body={"name": name, "description": desc, "icon": icon},
    )
    click.echo(json.dumps(result, indent=2))


@manifest.command("delete")
@click.argument("slug")
@click.pass_context
def manifest_delete(ctx: click.Context, slug: str) -> None:
    """Remove a manifest."""
    result = _api_request(ctx, "DELETE", f"/manifests/{slug}")
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# services
# ---------------------------------------------------------------------------


@main.group()
def services() -> None:
    """Service control commands."""


@services.command("list")
@click.pass_context
def services_list(ctx: click.Context) -> None:
    """List all services with systemd unit information."""
    url, token = _resolve_target(ctx)
    full_url = f"{url.rstrip('/')}/api/services"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(full_url, headers=headers, timeout=30)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError):
        click.echo(f"Error: could not connect to {url}", err=True)
        sys.exit(1)
    if resp.status_code >= 400:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)
    click.echo(json.dumps(resp.json(), indent=2))


@services.command("restart")
@click.argument("slug")
@click.pass_context
def services_restart(ctx: click.Context, slug: str) -> None:
    """Restart a single service by slug."""
    result = _api_request(ctx, "POST", f"/services/{slug}/restart")
    click.echo(json.dumps(result, indent=2))


@services.command("restart-all")
@click.pass_context
def services_restart_all(ctx: click.Context) -> None:
    """Restart all services (excludes frontdoor itself)."""
    result = _api_request(ctx, "POST", "/services/restart-all")
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------


@main.group()
def app() -> None:
    """App registration commands."""


@app.command("register")
@click.argument("slug")
@click.option(
    "--name", default="", help="Human-readable name (defaults to slug title-cased)"
)
@click.option("--description", default="", help="One-line description")
@click.option("--icon", default="", help="Emoji or Phosphor icon keyword")
@click.option("--internal-port", required=True, type=int, help="Port the app binds to")
@click.option("--external-port", required=True, type=int, help="Port Caddy exposes")
@click.option("--exec-start", required=True, help="systemd ExecStart command")
@click.option("--service-user", default="", help="OS user to run the service as")
@click.option("--kill-mode", default=None, help="systemd KillMode (e.g. 'process')")
@click.option(
    "--ws-path", multiple=True, help="WebSocket paths to bypass auth (repeatable)"
)
@click.pass_context
def app_register(
    ctx: click.Context,
    slug: str,
    name: str,
    description: str,
    icon: str,
    internal_port: int,
    external_port: int,
    exec_start: str,
    service_user: str,
    kill_mode: str | None,
    ws_path: tuple[str, ...],
) -> None:
    """Register a new app (Caddy config + systemd unit + manifest)."""
    body: dict = {
        "slug": slug,
        "name": name,
        "description": description,
        "icon": icon,
        "internal_port": internal_port,
        "external_port": external_port,
        "exec_start": exec_start,
        "service_user": service_user,
    }
    if kill_mode:
        body["kill_mode"] = kill_mode
    if ws_path:
        body["websocket_paths"] = list(ws_path)
    result = _api_request(ctx, "POST", "/apps", json_body=body)
    click.echo(json.dumps(result, indent=2))


@app.command("unregister")
@click.argument("slug")
@click.pass_context
def app_unregister(ctx: click.Context, slug: str) -> None:
    """Remove a registered app."""
    result = _api_request(ctx, "DELETE", f"/apps/{slug}")
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# known-apps
# ---------------------------------------------------------------------------


@main.group("known-apps")
def known_apps() -> None:
    """Pre-built app configuration commands."""


@known_apps.command("list")
@click.pass_context
def known_apps_list(ctx: click.Context) -> None:
    """List available known-app configurations."""
    result = _api_request(ctx, "GET", "/known-apps")
    click.echo(json.dumps(result, indent=2))


@known_apps.command("install")
@click.argument("appname")
@click.option("--service-user", default="", help="OS user to run the service as")
@click.pass_context
def known_apps_install(ctx: click.Context, appname: str, service_user: str) -> None:
    """Install a known-app configuration."""
    result = _api_request(
        ctx,
        "POST",
        f"/known-apps/{appname}/install",
        json_body={"service_user": service_user},
    )
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# token
# ---------------------------------------------------------------------------


@main.group()
def token() -> None:
    """API token management commands."""


@token.command("create")
@click.option("--name", required=True, help="Human-readable label for this token")
@click.pass_context
def token_create(ctx: click.Context, name: str) -> None:
    """Create a new API token (localhost or session auth only)."""
    result = _api_request(ctx, "POST", "/tokens", json_body={"name": name})
    click.echo(json.dumps(result, indent=2))
    click.echo("\nSave this token — it will not be shown again.", err=True)


@token.command("list")
@click.pass_context
def token_list(ctx: click.Context) -> None:
    """List all tokens (never shows hashes or raw values)."""
    result = _api_request(ctx, "GET", "/tokens")
    click.echo(json.dumps(result, indent=2))


@token.command("revoke")
@click.argument("token_id")
@click.pass_context
def token_revoke(ctx: click.Context, token_id: str) -> None:
    """Revoke a token by its ID."""
    result = _api_request(ctx, "DELETE", f"/tokens/{token_id}")
    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# box
# ---------------------------------------------------------------------------


@main.group()
def box() -> None:
    """Fleet box alias management (local config only)."""


@box.command("list")
def box_list() -> None:
    """List configured boxes."""
    config = _load_box_config()
    boxes = config.get("boxes", {})
    defaults = config.get("defaults", {})
    result = []
    for name, box_conf in boxes.items():
        entry: dict = {"name": name, "url": box_conf.get("url", "")}
        if name == defaults.get("box"):
            entry["default"] = True
        result.append(entry)
    click.echo(json.dumps(result, indent=2))


@box.command("add")
@click.argument("name")
@click.option("--url", required=True, help="URL of the frontdoor instance")
@click.option("--token", default=None, help="API token for this box")
def box_add(name: str, url: str, token: str | None) -> None:
    """Add a named box alias to local config."""
    config_path = Path.home() / ".config" / "frontdoor" / "cli.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = _load_box_config()
    if "boxes" not in config:
        config["boxes"] = {}
    config["boxes"][name] = {"url": url}
    if token:
        config["boxes"][name]["token"] = token

    lines = []
    if "defaults" in config:
        lines.append("[defaults]")
        for k, v in config["defaults"].items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    for box_name, box_conf in config.get("boxes", {}).items():
        lines.append(f"[boxes.{box_name}]")
        for k, v in box_conf.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    config_path.write_text("\n".join(lines))
    click.echo(json.dumps({"status": "added", "name": name, "url": url}))


@box.command("remove")
@click.argument("name")
def box_remove(name: str) -> None:
    """Remove a box alias from local config."""
    config = _load_box_config()
    boxes = config.get("boxes", {})
    if name not in boxes:
        click.echo(f"Error: box '{name}' not found", err=True)
        sys.exit(1)
    del boxes[name]

    config_path = Path.home() / ".config" / "frontdoor" / "cli.toml"
    lines = []
    if "defaults" in config:
        lines.append("[defaults]")
        for k, v in config["defaults"].items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    for box_name, box_conf in boxes.items():
        lines.append(f"[boxes.{box_name}]")
        for k, v in box_conf.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    config_path.write_text("\n".join(lines))
    click.echo(json.dumps({"status": "removed", "name": name}))
