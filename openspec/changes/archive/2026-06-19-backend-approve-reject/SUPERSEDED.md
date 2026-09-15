# Supersession note

The archived `items[]` bulk request contract records the decision in force when this change was closed. It is preserved as history and is no longer normative.

Current authority is `openspec/specs/backend-approve-reject/spec.md`: bulk approve uses `{event_ids:[...]}` and bulk reject uses `{event_ids:[...], action:"restore"|"quarantine"}`. This is a breaking migration with no legacy alias; requests containing `items` receive 422.
