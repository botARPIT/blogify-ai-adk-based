"""Normalizer unit tests.

Fully network-independent: no model, no Redis, no Postgres, no ADK runner.
"""

from __future__ import annotations

import pytest

from src.normalizer import (
    NormalizationError,
    extract_raw_output,
    normalize_editor_review,
    normalize_intent,
    normalize_outline,
)

# ---------------------------------------------------------------------------
# Fixtures: the two Markdown forms observed from Ollama-class models.
# ---------------------------------------------------------------------------

BOLD_FORM = """**Title:** Building Reliable Blog Pipelines

**Section 1: Why Pipelines Fail**
* Goal: Establish the failure modes
* Target Word Count: 150 words

**Section 2: Designing the Graph**
* Goal: Show the graph structure
* Target Word Count: 180 words

**Section 3: Shipping It**
* Goal: Cover rollout
* Target Word Count: 200 words
"""

HEADING_FORM = """# Building Reliable Blog Pipelines

### Section 1 – Why Pipelines Fail
**Goal:** Establish the failure modes
**Target Word Count:** 120–180

### Section 2 – Designing the Graph
**Goal:** Show the graph structure
**Target Word Count:** 150 words

### Section 3 – Shipping It
**Goal:** Cover rollout
**Target Word Count:** 160 words
"""

VALID_JSON = """{
  "title": "Building Reliable Blog Pipelines",
  "sections": [
    {"id": "s1", "heading": "Why", "goal": "Establish", "target_words": 150},
    {"id": "s2", "heading": "Design", "goal": "Show", "target_words": 150},
    {"id": "s3", "heading": "Ship", "goal": "Cover", "target_words": 150}
  ],
  "estimated_total_words": 450
}"""


def _sections(n: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"s{i}",
            "heading": f"Section {i}",
            "goal": f"Goal {i}",
            "target_words": 120,
        }
        for i in range(1, n + 1)
    ]


class TestOutlineJson:
    def test_valid_json_round_trips(self):
        outline = normalize_outline(VALID_JSON)
        assert outline.title == "Building Reliable Blog Pipelines"
        assert len(outline.sections) == 3
        assert outline.estimated_total_words == 450

    def test_fenced_json_is_accepted(self):
        outline = normalize_outline(f"```json\n{VALID_JSON}\n```")
        assert outline.title == "Building Reliable Blog Pipelines"

    def test_bare_fence_is_accepted(self):
        outline = normalize_outline(f"```\n{VALID_JSON}\n```")
        assert len(outline.sections) == 3

    def test_surrounding_prose_is_not_tolerated_for_json(self):
        """A JSON-looking object embedded in prose is still a format error."""
        with pytest.raises(NormalizationError):
            normalize_outline(f"Sure! Here it is:\n{VALID_JSON}")


class TestOutlineMarkdown:
    def test_bold_form_parses(self):
        outline = normalize_outline(BOLD_FORM)
        assert outline.title == "Building Reliable Blog Pipelines"
        assert len(outline.sections) == 3
        assert outline.sections[0].heading == "Why Pipelines Fail"
        assert outline.sections[0].goal == "Establish the failure modes"
        assert outline.sections[0].target_words == 150

    def test_heading_form_parses(self):
        outline = normalize_outline(HEADING_FORM)
        assert len(outline.sections) == 3
        assert outline.sections[0].heading == "Why Pipelines Fail"
        assert outline.sections[0].goal == "Establish the failure modes"

    def test_word_count_range_takes_its_lower_bound(self):
        outline = normalize_outline(HEADING_FORM)
        assert outline.sections[0].target_words == 120

    @pytest.mark.parametrize("dash", ["–", "—", "-", "~", "to"])
    def test_word_count_range_spellings(self, dash):
        raw = HEADING_FORM.replace("120–180", f"120{dash}180")
        assert normalize_outline(raw).sections[0].target_words == 120

    def test_section_ids_are_derived_from_headings(self):
        outline = normalize_outline(BOLD_FORM)
        assert [s.id for s in outline.sections] == [
            "section_1",
            "section_2",
            "section_3",
        ]

    def test_total_words_summed_when_not_stated(self):
        outline = normalize_outline(BOLD_FORM)
        assert outline.estimated_total_words == 150 + 180 + 200

    def test_both_markdown_forms_yield_equivalent_shapes(self):
        bold = normalize_outline(BOLD_FORM)
        heading = normalize_outline(HEADING_FORM)
        assert bold.title == heading.title
        assert len(bold.sections) == len(heading.sections)


class TestOutlineSectionCountBounds:
    def test_more_than_seven_sections_is_rejected(self):
        payload = {
            "title": "Too many",
            "sections": _sections(8),
            "estimated_total_words": 960,
        }
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert any("sections" in p for p in exc.value.field_paths)

    def test_fewer_than_three_sections_is_rejected(self):
        payload = {"title": "Too few", "sections": _sections(2), "estimated_total_words": 240}
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert any("sections" in p for p in exc.value.field_paths)

    @pytest.mark.parametrize("count", [3, 5, 7])
    def test_bounds_three_through_seven_are_accepted(self, count):
        payload = {
            "title": "In range",
            "sections": _sections(count),
            "estimated_total_words": 120 * count,
        }
        assert len(normalize_outline(_dumps(payload)).sections) == count


class TestOutlineMissingFields:
    def test_missing_title_fails(self):
        payload = {
            "sections": _sections(3),
            "estimated_total_words": 360,
        }
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert "title" in exc.value.field_paths

    def test_missing_goal_fails(self):
        sections = _sections(3)
        del sections[1]["goal"]
        payload = {"title": "T", "sections": sections, "estimated_total_words": 360}
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert any("goal" in p for p in exc.value.field_paths)

    def test_missing_target_count_fails(self):
        sections = _sections(3)
        del sections[2]["target_words"]
        payload = {"title": "T", "sections": sections, "estimated_total_words": 360}
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert any("target_words" in p for p in exc.value.field_paths)

    def test_markdown_missing_goal_names_the_section(self):
        raw = """**Title:** T

**Section 1: A**
* Target Word Count: 120 words

**Section 2: B**
* Goal: g
* Target Word Count: 120 words

**Section 3: C**
* Goal: g
* Target Word Count: 120 words
"""
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(raw)
        assert any("goal" in p for p in exc.value.field_paths)
        assert exc.value.output_format == "markdown"

    def test_markdown_missing_target_count_names_the_section(self):
        raw = """**Title:** T

**Section 1: A**
* Goal: g

**Section 2: B**
* Goal: g
* Target Word Count: 120 words

**Section 3: C**
* Goal: g
* Target Word Count: 120 words
"""
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(raw)
        assert any("target_words" in p for p in exc.value.field_paths)

    def test_markdown_missing_title_fails(self):
        raw = """**Section 1: A**
* Goal: g
* Target Word Count: 120 words
"""
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(raw)
        assert exc.value.field_paths == ["title"]

    def test_out_of_range_target_words_is_rejected(self):
        payload = {
            "title": "T",
            "sections": [{**_sections(3)[0], "target_words": 9000}, *_sections(2)[1:]],
            "estimated_total_words": 400,
        }
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert any("target_words" in p for p in exc.value.field_paths)


class TestNoSemanticAliasing:
    """Schema mismatches must stay visible, never be silently corrected."""

    def test_total_word_count_is_not_aliased_to_estimated_total_words(self):
        payload = {
            "title": "T",
            "sections": _sections(3),
            "total_word_count": 360,
        }
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert "estimated_total_words" in exc.value.field_paths

    def test_unknown_field_is_not_silently_absorbed(self):
        payload = {
            "title": "T",
            "sections": _sections(3),
            "estimated_total_words": 360,
            "totally_unexpected": 1,
        }
        # Pydantic ignores unknown keys, so the outline still validates: what
        # matters is that the *known* key was not invented from the unknown one.
        assert normalize_outline(_dumps(payload)).title == "T"

    def test_goal_is_not_inferred_from_a_differently_named_field(self):
        sections = _sections(3)
        del sections[0]["goal"]
        sections[0]["objective"] = "smuggled"
        payload = {"title": "T", "sections": sections, "estimated_total_words": 360}
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert any("goal" in p for p in exc.value.field_paths)


class TestOutlineUnusableInput:
    def test_arbitrary_prose_is_rejected(self):
        with pytest.raises(NormalizationError):
            normalize_outline(
                "Sure! I'd be happy to help. What topic would you like the blog to cover?"
            )

    def test_empty_output_is_rejected(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_outline("")
        assert exc.value.output_format == "empty"
        assert "outline_agent" in exc.value.agent

    def test_whitespace_only_output_is_rejected(self):
        with pytest.raises(NormalizationError):
            normalize_outline("   \n\t\n  ")

    def test_json_array_is_rejected(self):
        with pytest.raises(NormalizationError):
            normalize_outline("[1, 2, 3]")

    def test_malformed_json_is_reported_as_json_format(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_outline('{"title": "T", "sections": [')
        assert exc.value.output_format == "json"


class TestNormalizationIsDeterministic:
    def test_same_input_yields_equal_output(self):
        assert normalize_outline(BOLD_FORM) == normalize_outline(BOLD_FORM)

    def test_repeated_calls_are_stable_for_json(self):
        assert normalize_outline(VALID_JSON) == normalize_outline(VALID_JSON)

    def test_normalizer_makes_no_network_calls(self, monkeypatch):
        import socket

        def forbidden(*_args, **_kwargs):
            raise AssertionError("normalizer attempted network access")

        monkeypatch.setattr(socket, "socket", forbidden)
        monkeypatch.setattr(socket, "create_connection", forbidden)
        assert normalize_outline(BOLD_FORM).title


class TestErrorReporting:
    def test_error_locates_the_failure(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_outline("")
        error = exc.value
        assert error.workflow == "blog_generation"
        assert error.stage == "outline"
        assert error.agent == "outline_agent"
        assert error.output_format == "empty"

    def test_error_message_carries_structured_context(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_outline("")
        message = str(exc.value)
        assert "workflow=blog_generation" in message
        assert "stage=outline" in message
        assert "agent=outline_agent" in message

    def test_error_reports_field_paths(self):
        payload = {"title": "T", "sections": _sections(2), "estimated_total_words": 240}
        with pytest.raises(NormalizationError) as exc:
            normalize_outline(_dumps(payload))
        assert exc.value.field_paths


class TestIntent:
    def test_valid_intent(self):
        intent = normalize_intent('{"status": "CLEAR", "message": "Good topic"}')
        assert intent.status == "CLEAR"
        assert intent.message == "Good topic"

    def test_fenced_intent(self):
        intent = normalize_intent('```json\n{"status": "CLEAR", "message": "ok"}\n```')
        assert intent.status == "CLEAR"

    def test_missing_field_fails(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_intent('{"status": "CLEAR"}')
        assert "message" in exc.value.field_paths

    def test_non_json_fails(self):
        with pytest.raises(NormalizationError):
            normalize_intent("This topic looks fine to me.")

    def test_error_identifies_intent_stage(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_intent("nope")
        assert exc.value.stage == "intent"
        assert exc.value.agent == "intent_classifier"


class TestEditorReview:
    def test_approved_review(self):
        review = normalize_editor_review(
            '{"approved": true, "feedback": "", "final_blog": "# Done", "sources_section": "Sources"}'
        )
        assert review.approved is True
        assert review.final_blog == "# Done"

    def test_rejected_review(self):
        review = normalize_editor_review(
            '{"approved": false, "feedback": "Too short", "final_blog": "", "sources_section": ""}'
        )
        assert review.approved is False
        assert review.feedback == "Too short"

    def test_missing_field_fails(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_editor_review('{"approved": true, "feedback": ""}')
        assert any(p in ("final_blog", "sources_section") for p in exc.value.field_paths)

    def test_non_json_fails(self):
        with pytest.raises(NormalizationError):
            normalize_editor_review("The draft looks good to me!")

    def test_error_identifies_editor_stage(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_editor_review("nope")
        assert exc.value.stage == "editor"
        assert exc.value.agent == "editor_agent"


class TestExtractRawOutput:
    def test_plain_string_passes_through(self):
        assert extract_raw_output("hello") == "hello"

    def test_none_becomes_empty_string(self):
        assert extract_raw_output(None) == ""

    def test_dict_becomes_json(self):
        import json

        assert json.loads(extract_raw_output({"a": 1})) == {"a": 1}

    def test_bytes_are_decoded(self):
        assert extract_raw_output(b"hello") == "hello"

    def test_pydantic_model_becomes_json(self):
        from src.models.schemas import IntentSchema

        raw = extract_raw_output(IntentSchema(status="CLEAR", message="m"))
        assert '"CLEAR"' in raw

    def test_adk_content_becomes_text(self):
        from google.genai import types

        content = types.Content(
            role="model", parts=[types.Part(text="part one "), types.Part(text="part two")]
        )
        assert extract_raw_output(content) == "part one part two"

    def test_event_with_content_becomes_text(self):
        from google.adk.events.event import Event
        from google.genai import types

        event = Event(
            author="outline_agent",
            content=types.Content(role="model", parts=[types.Part(text="from event")]),
        )
        assert extract_raw_output(event) == "from event"

    def test_arbitrary_object_becomes_its_string_form(self):
        class Thing:
            def __str__(self) -> str:
                return "thing"

        assert extract_raw_output(Thing()) == "thing"


def _dumps(payload: dict) -> str:
    import json

    return json.dumps(payload)
