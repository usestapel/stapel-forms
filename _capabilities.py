"""stapel-forms capabilities.json emitter — thin shim over stapel_tools.capabilities.

Two different things wear the word "capability" in this repo and the file
this module writes carries both, so the distinction is worth stating once:

* an **axis** is a configuration switch that changes what the PRODUCT may
  do (may a form ask for a colour, are respondent IPs kept). The generic
  mechanism in ``stapel_tools.capabilities`` derives those from
  ``conf.DEFAULTS``;
* a **workspace capability** is a permission string — ``forms.view``,
  ``forms.responses.manage`` — that says who may drive an endpoint. Those
  are what a host grants in ``STAPEL_WORKSPACES["ROLES"]`` and what a UI
  gates a control on.

Until 0.3.0 this artifact projected only the first kind, so
``forms.responses.manage`` existed in ``authz.py``, was enforced on two
endpoints, and appeared in NO machine-readable artifact this module ships.
A frontend could therefore not tell whether the responses surface should be
offered at all, and its only options were to show it to everyone or to hide
it from everyone. The ``capabilities`` section below closes that.

Why it is derived from ``docs/schema.json`` rather than restated here: the
capability lands in the schema as ``x-stapel-capability``, written by
``views.CapabilityAwareAutoSchema`` off the very attribute
``views.gated(...)`` stamps on the handler and ``views._access_error``
reads to authorize the request. One decorator, one attribute, and both the
projection and the enforcement hang off it — a capability cannot be
published for an operation that will not actually be gated on it, because
there is no second place to type the string.
"""
from pathlib import Path

# The stable-JSON pinning of the contract pipeline. Imported rather than
# re-implemented: a second formatter here would make `make contract-check`
# fail on whitespace the day stapel-tools changes its pinning.
from stapel_tools.capabilities import (
    _stable_json,
    axis_group_rules,
    emit_capabilities,
)

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _capability_section(out: Path, meta: dict, enforced: tuple) -> list:
    """Build the ``capabilities`` section: derived operations, curated prose.

    Mirrors the shape of an ``axes`` entry on purpose (``key`` +
    ``gates.operations`` + ``curated``), so a reader who knows one knows the
    other and a consumer walks both with the same code.

    Every direction of drift is a loud emission error:

    * a capability the module enforces with no curated entry, or a curated
      entry for a capability nothing enforces — the same missing/extra check
      the axes already get;
    * a capability that ``authz`` enforces but no operation projects. That
      one is the real prize: it means a permission string is grantable and
      documented while no endpoint asks for it, which is precisely the
      "answers yes, endpoint answers 403" shape inverted.
    """
    import json

    schema = json.loads((out / "schema.json").read_text())

    operations: dict[str, list[str]] = {cap: [] for cap in enforced}
    for path_item in schema.get("paths", {}).values():
        for method, op in path_item.items():
            if method not in _HTTP_METHODS:
                continue
            capability = op.get("x-stapel-capability")
            if capability is None:
                continue
            if capability not in operations:
                raise SystemExit(
                    f"capabilities: schema.json projects {capability!r} on "
                    f"{op.get('operationId')!r}, but stapel_forms.authz does not "
                    "enforce it — the contract and the gate disagree."
                )
            operations[capability].append(op["operationId"])

    ungated = sorted(cap for cap, ops in operations.items() if not ops)
    if ungated:
        raise SystemExit(
            f"capabilities: {ungated} are enforced by stapel_forms.authz but no "
            "operation in schema.json projects them — either an admin handler "
            "lost its @gated(...) declaration, or the action is dead and must "
            "leave ACTION_CAPABILITIES."
        )

    curated = meta.get("capabilities", {})
    missing = [c for c in enforced if c not in curated]
    extra = [c for c in curated if c not in operations]
    if missing or extra:
        raise SystemExit(
            "capabilities: curated meta out of sync with the enforced capability "
            f"set — missing from capabilities.meta.json: {missing or 'none'}; "
            f"stale in capabilities.meta.json: {extra or 'none'}."
        )

    section = []
    for capability in enforced:
        entry = curated[capability]
        for field in ("summary", "business_label"):
            if not entry.get(field):
                raise SystemExit(
                    f"capabilities: capability {capability!r} lacks a non-empty "
                    f"{field!r} in docs/capabilities.meta.json"
                )
        gates = {"operations": sorted(operations[capability])}
        # Same optional `behavior` field an axis entry carries: what a
        # consumer must know about the gate beyond which routes it opens.
        # Here it is the one thing this capability CANNOT tell a client —
        # see the note in docs/capabilities.meta.json.
        if entry.get("behavior"):
            gates["behavior"] = entry["behavior"]
        section.append(
            {
                "key": capability,
                "gates": gates,
                "curated": {
                    "summary": entry["summary"],
                    "business_label": entry["business_label"],
                },
            }
        )
    return section


def main(argv=None):
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="stapel-forms-capabilities",
        description="Emit docs/capabilities.json (fourth contract artifact): "
        "config axes from conf.py DEFAULTS + the urls.py gate registry, and the "
        "workspace capability projection derived from schema.json.",
    )
    parser.add_argument(
        "--out",
        default="docs",
        help="Output directory; must already contain schema.json (default: docs).",
    )
    args = parser.parse_args(argv)

    from stapel_forms._codegen import _configure

    _configure()
    from stapel_forms.authz import CAPABILITIES
    from stapel_forms.conf import DEFAULTS
    from stapel_forms.urls_v1 import GATE_REGISTRY

    repo = Path(__file__).resolve().parent
    out = Path(args.out)

    # The CTO-facing axes are the ones that change what the PRODUCT is
    # allowed to do, not how fast it runs: which field kinds a form may
    # use, whether respondent IPs are stored, how long answers are kept,
    # and whether public forms may run without a captcha. Throttle rates,
    # page sizes, cooldown seconds and the caps are tuning — they bound
    # abuse, they do not change the deal with the respondent.
    axes = {
        "FIELD_KINDS",
        "STORE_CLIENT_META",
        "RETENTION_DAYS",
        "ALLOW_UNCAPTCHAED_PUBLIC",
        "ACCEPT_PREVIOUS_VERSION_SECONDS",
    }
    doc = emit_capabilities(
        out,
        repo=repo,
        canonical_prefix="/forms/api/v1",
        defaults=DEFAULTS,
        registry=GATE_REGISTRY,
        is_axis=lambda k: k in axes,
        axis_group=axis_group_rules(
            exact={
                "FIELD_KINDS": "forms.schema",
                "STORE_CLIENT_META": "forms.privacy",
                "RETENTION_DAYS": "forms.privacy",
                "ALLOW_UNCAPTCHAED_PUBLIC": "forms.public",
                "ACCEPT_PREVIOUS_VERSION_SECONDS": "forms.public",
            }
        ),
    )

    meta = json.loads((repo / "docs" / "capabilities.meta.json").read_text())
    section = _capability_section(out, meta, CAPABILITIES)

    # Rebuild in a fixed key order — `capabilities` sits next to `axes`
    # because the two answer the paired questions "what may this deployment
    # do" and "who in it may do it".
    ordered = {}
    for key, value in doc.items():
        ordered[key] = value
        if key == "axes":
            ordered["capabilities"] = section
    (out / "capabilities.json").write_text(_stable_json(ordered))

    gated = sum(1 for a in ordered["axes"] if a["gates"]["operations"])
    print(
        f"{ordered['module']} capabilities: {len(ordered['axes'])} axes ({gated} "
        f"gating operations), {len(section)} workspace capabilities over "
        f"{sum(len(c['gates']['operations']) for c in section)} gated operations, "
        f"{len(ordered.get('surface') or [])} surface entries, "
        f"{ordered['operations_total']} operations total → "
        f"{args.out}/capabilities.json",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
