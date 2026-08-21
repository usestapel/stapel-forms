"""The attributes adapter — every deviation the spike found, pinned.

These tests exist because the underlying engine is shared with listings and
categories, whose needs differ from a public form's. If a future
stapel-attributes release changes one of these behaviours, this file fails
here rather than at a respondent's browser.
"""
import pytest

from stapel_forms import schema as schema_mod
from stapel_forms.errors import (
    ERR_400_DUPLICATE_SLUG,
    ERR_400_EMPTY_SCHEMA,
    ERR_400_INVALID_SCHEMA,
    ERR_400_KIND_NOT_ALLOWED,
    ERR_400_TOO_MANY_FIELDS,
)

ALL_KINDS = {
    "string", "int", "float", "bool", "select", "date", "header",
    "hex_color", "hierarchical_select", "convertible_unit",
}


def _validate(schema, kinds=None, max_fields=64):
    schema_mod.validate_schema(
        schema_mod.normalize_schema(schema),
        allowed_kinds=kinds or ALL_KINDS,
        max_fields=max_fields,
    )


def test_bare_field_list_is_accepted_as_a_schema(simple_schema):
    normalized = schema_mod.normalize_schema(simple_schema["fields"])
    assert normalized["meta"] == {}
    assert len(normalized["fields"]) == 4


@pytest.mark.parametrize("raw", ["nope", 7, None, {"fields": "nope"}, {"fields": [1]}])
def test_non_schema_shapes_refuse(raw):
    with pytest.raises(schema_mod.SchemaInvalid) as exc:
        schema_mod.normalize_schema(raw)
    assert exc.value.error_key == ERR_400_INVALID_SCHEMA


def test_valid_schema_passes(simple_schema):
    _validate(simple_schema)


def test_empty_schema_refuses():
    with pytest.raises(schema_mod.SchemaInvalid) as exc:
        _validate({"fields": []})
    assert exc.value.error_key == ERR_400_EMPTY_SCHEMA


def test_field_cap_refuses():
    fields = [
        {"slug": f"f{i}", "name": f"F{i}", "config": {"type": "string"}} for i in range(5)
    ]
    with pytest.raises(schema_mod.SchemaInvalid) as exc:
        _validate({"fields": fields}, max_fields=4)
    assert exc.value.error_key == ERR_400_TOO_MANY_FIELDS


def test_duplicate_slug_refuses():
    fields = [
        {"slug": "a", "name": "A", "config": {"type": "string"}},
        {"slug": "a", "name": "A again", "config": {"type": "int"}},
    ]
    with pytest.raises(schema_mod.SchemaInvalid) as exc:
        _validate({"fields": fields})
    assert exc.value.error_key == ERR_400_DUPLICATE_SLUG


def test_kind_outside_the_allowlist_refuses():
    fields = [{"slug": "a", "name": "A", "config": {"type": "int"}}]
    with pytest.raises(schema_mod.SchemaInvalid) as exc:
        _validate({"fields": fields}, kinds={"string"})
    assert exc.value.error_key == ERR_400_KIND_NOT_ALLOWED
    assert exc.value.params["kind"] == "int"


def test_unknown_kind_refuses():
    fields = [{"slug": "a", "name": "A", "config": {"type": "quantum"}}]
    with pytest.raises(schema_mod.SchemaInvalid):
        _validate({"fields": fields}, kinds=ALL_KINDS | {"quantum"})


def test_typoed_config_key_refuses_rather_than_silently_dropping():
    # The engine's dataclass parser drops unknown keys, so `max_length`
    # (snake) would be a length cap that silently does not exist.
    fields = [{"slug": "a", "name": "A", "config": {"type": "string", "max_length": 5}}]
    with pytest.raises(schema_mod.SchemaInvalid) as exc:
        _validate({"fields": fields})
    assert exc.value.error_key == ERR_400_INVALID_SCHEMA
    assert exc.value.params["key"] == "max_length"


def test_camelcase_config_key_is_the_real_one(simple_schema):
    _validate(simple_schema)
    errors, unknown = schema_mod.validate_answers(
        simple_schema, {"full_name": "A" * 100, "plan": "pro"}
    )
    assert unknown == []
    assert [e.code for e in errors] == ["error.400.feature_above_maximum"]
    assert errors[0].params["ref_value"] == 40


def test_mandatory_missing_is_reported_per_field(simple_schema):
    errors, unknown = schema_mod.validate_answers(simple_schema, {})
    assert unknown == []
    assert sorted(e.field for e in errors) == ["full_name", "plan"]
    assert all(e.code == "error.400.feature_mandatory_missing" for e in errors)


def test_field_param_is_present_for_the_frontend(simple_schema):
    """The engine names it `slug`; the fleet's frontend reads `params.field`."""
    errors, _ = schema_mod.validate_answers(simple_schema, {"plan": "pro"})
    assert errors[0].params["field"] == errors[0].field == "full_name"
    assert errors[0].params["slug"] == "full_name"


def test_unknown_slug_is_refused_not_ignored(simple_schema):
    errors, unknown = schema_mod.validate_answers(
        simple_schema, {"full_name": "Ann", "plan": "pro", "evil": "x"}
    )
    assert unknown == ["evil"]
    assert errors == []


def test_answering_a_header_is_refused(simple_schema):
    _errors, unknown = schema_mod.validate_answers(
        simple_schema, {"full_name": "Ann", "plan": "pro", "sec": "smuggled"}
    )
    assert unknown == ["sec"]


def test_non_object_answers_are_signalled(simple_schema):
    errors, unknown = schema_mod.validate_answers(simple_schema, ["nope"])
    assert unknown is None and errors == []


def test_wrong_type_reports_the_offending_field(simple_schema):
    errors, _ = schema_mod.validate_answers(
        simple_schema, {"full_name": "Ann", "plan": "pro", "age": "old"}
    )
    assert [(e.field, e.code) for e in errors] == [
        ("age", "error.400.feature_invalid_type")
    ]


def test_bad_choice_carries_the_allowed_options(simple_schema):
    errors, _ = schema_mod.validate_answers(
        simple_schema, {"full_name": "Ann", "plan": "gold"}
    )
    assert errors[0].code == "error.400.feature_not_in_options"
    assert errors[0].params["ref_value"] == ["basic", "pro"]


def test_optional_field_may_be_omitted_or_null(simple_schema):
    for answers in ({"full_name": "Ann", "plan": "pro"},
                    {"full_name": "Ann", "plan": "pro", "age": None}):
        errors, unknown = schema_mod.validate_answers(simple_schema, answers)
        assert (errors, unknown) == ([], [])


def test_to_dao_stores_typed_shapes_and_regenerates_headers(simple_schema):
    dao = schema_mod.to_dao(simple_schema, {"full_name": "Ann", "plan": "pro", "age": 33})
    assert dao["full_name"]["value"] == "Ann"
    assert dao["age"]["value"] == 33
    assert dao["plan"]["value"] == ["pro"]
    # The header is auto-generated from the config, not from any input.
    assert dao["sec"]["type"] == "header"


def test_answer_columns_skip_headers(simple_schema):
    assert schema_mod.answer_columns(simple_schema) == [
        ("full_name", "Full name"),
        ("age", "Age"),
        ("plan", "Plan"),
    ]
