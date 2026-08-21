"""stapel-forms capabilities.json emitter — thin shim over stapel_tools.capabilities."""
from pathlib import Path

from stapel_tools.capabilities import axis_group_rules, run_capabilities_cli


def main(argv=None):
    from stapel_forms._codegen import _configure

    _configure()
    from stapel_forms.conf import DEFAULTS
    from stapel_forms.urls_v1 import GATE_REGISTRY

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
    return run_capabilities_cli(
        argv,
        repo=Path(__file__).resolve().parent,
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
        prog="stapel-forms-capabilities",
    )


if __name__ == "__main__":
    raise SystemExit(main())
