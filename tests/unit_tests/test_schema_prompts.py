from agent.prompts import LEVEL_INSTRUCTIONS, SCHEMA_GENERATOR_PROMPT


def test_conceptual_prompt_preserves_weak_entity_semantics() -> None:
    prompt = LEVEL_INSTRUCTIONS["conceptual"]

    assert "partial key" in prompt
    assert 'kind: "weak"' in prompt
    assert "identifying" in prompt
    assert "optional: false" in prompt
    assert "standalone surrogate" in prompt


def test_relational_prompts_map_weak_entity_to_composite_key() -> None:
    for level in ("logical", "physical"):
        prompt = LEVEL_INSTRUCTIONS[level]

        assert "Weak-entity mapping is mandatory" in prompt
        assert "publication_id" in prompt
        assert "issue_number" in prompt
        assert "date_issued" in prompt
        assert "composite PK" in prompt
        assert "independent identity" in prompt


def test_prompts_do_not_make_composite_pk_components_individually_unique() -> None:
    for level in ("logical", "physical"):
        prompt = LEVEL_INSTRUCTIONS[level]

        assert "Composite-PK components" in prompt or "composite PK" in prompt
        assert "unique: false" in prompt
        assert "independently unique" in prompt


def test_generator_self_check_rejects_surrogate_weak_entity_identity() -> None:
    assert "owner-key + partial-key identity" in SCHEMA_GENERATOR_PROMPT
    assert "No surrogate" in SCHEMA_GENERATOR_PROMPT
