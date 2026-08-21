"""A host-registered feature type, reached through ``EXTRA_TYPES``.

Test double for the one seam the field-kinds endpoint exists to serve: a
kind this package has never heard of must reach the builder with its own
config form and no release of stapel-forms or of the React pair. It
subclasses the built-in ``bool`` handler rather than re-implementing a
config/dto/dao triad — what is under test is the REGISTRY path, not the
validation of a new value shape.
"""
from stapel_attributes.config_form import FormField
from stapel_attributes.registry import register_feature_type
from stapel_attributes.types.bool.type import BoolFeatureType

EXTRA_TYPE_PATH = "stapel_forms.tests.extra_type"
EXTRA_TYPE_SLUG = "consent"


@register_feature_type
class ConsentFeatureType(BoolFeatureType):
    slug = EXTRA_TYPE_SLUG
    name = "Consent"

    def config_form(self):
        return [
            FormField(
                name="policyUrl",
                kind="text",
                label_key="admin.attributes.form.consent.policyUrl",
                required=True,
            )
        ]
