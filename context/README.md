# context/ — your client's documents (git-ignored)

Drop the agent's own documents here, then point `config/clients/<you>.yaml` at
them. Nothing in this directory is committed: it contains real customer data.

Minimum to run:

| File | What it is | Required |
|---|---|---|
| `disposition_definitions.xlsx` | The taxonomy: group / sub / expanded, decision rules, engine codes. Must also carry the output-format sheet, or point `inputs.output_format` elsewhere. | yes |
| `redial_test_matrix.xlsx` | Re-dial expectations + scheduling logic. Seeds the callback expectations. | recommended |
| `interaction_report.xlsx` | Real interactions, confidences, and any human-annotated classifier corrections. Drives empirical rival ranking. | recommended |
| `system_prompt.md` | The agent's own prompt. Constrains synthetic transcripts to sound like this agent. | recommended |
| anything else | Config-design docs, UAT sheets, objection libraries. List under `inputs.extras`. | optional |

Run `dispogen preflight --client <you>` — it tells you exactly which of these is
missing, malformed, or has drifted since the last run.
