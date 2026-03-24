"""
Prompt builder for FormFillerAgent.

Constructs a prompt from a FormFillerInput that asks the LLM to produce
contextually appropriate fill values for each form field.
"""

from __future__ import annotations

from carto.domain.inferences import FormFillerInput


def _format_fields(input: FormFillerInput) -> str:
    if not input.form_fields:
        return "No fields provided."
    lines: list[str] = []
    for i, field in enumerate(input.form_fields):
        parts = [f"[{i}]"]
        if field.css_selector:
            parts.append(f"selector=\"{field.css_selector}\"")
        parts.append(f"name={field.name or '?'}")
        parts.append(f"kind={field.kind}")
        if field.label:
            parts.append(f"label=\"{field.label}\"")
        if field.semantic_meaning:
            parts.append(f"meaning=\"{field.semantic_meaning}\"")
        parts.append(f"required={field.required}")
        if field.options:
            parts.append(f"options={field.options}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def build_form_filler_prompt(input: FormFillerInput) -> str:
    """Build the full prompt for the FormFillerAgent."""
    login_context = ""
    if input.is_login_form:
        login_context = f"""
## Login Form Context
This is a login form. Use the provided credentials:
- Username/email: {input.role_username or "(not provided)"}
- Password: {input.role_password or "(not provided)"}

If CSRF fields are present, preserve their existing values.
CSRF field name: {input.csrf_field_name or "(none detected)"}
"""

    return f"""You are a form-filling agent for an autonomous web mapper.
Generate appropriate values for each form field.

## Page Context
- URL: {input.page_url}
- Page purpose: {input.page_summary or "(unknown)"}
- Is login form: {input.is_login_form}
- Role: {input.role_name or "(default)"}
{login_context}
## Form Fields
{_format_fields(input)}

## Guidelines
- For login forms, use the provided credentials.
- For CSRF/XSRF hidden fields, DO NOT generate a value — set value to "" and note "preserve existing" in rationale.
- For search fields, use a reasonable test query.
- For email fields, use a plausible test email.
- For text inputs, use contextually appropriate values.
- For select dropdowns, pick the first non-empty option.
- For checkboxes, leave unchecked unless required.
- For password fields outside login forms, use a safe test password like "TestPass123!".
- Never use real credentials outside of the provided role context.

## Response Format

Return a JSON object with:
- **form_css_selector**: CSS selector for the form element (if known).
- **field_instructions**: List of fill instructions, each with:
  - **css_selector**: CSS selector for the field.
  - **value**: The value to fill.
  - **rationale**: Why this value was chosen.
- **should_submit**: Whether to submit the form after filling.
- **is_login_form**: Whether this is a login form.
- **auth_field_selectors**: CSS selectors of fields containing auth credentials.

Return ONLY the JSON object."""
