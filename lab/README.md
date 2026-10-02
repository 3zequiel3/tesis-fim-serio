# lab/ — evaluation harness

This directory holds the experiment harness exactly as it was used for the
`v3.0-tesis` and `v4.0-tesis` evaluation runs. It was copied verbatim from
`~/fim-lab/` (scripts and compose overrides only; run outputs, generated
certificates and private keys were excluded).

Absolute paths inside the scripts (`/home/ezequiel/...`, `~/fim-lab`) are kept
on purpose so this commit records what actually ran. Later commits adapt the
harness for the `v5.0-tesis` candidate (see `tesis/cierre/` lab guide, items
L-11 to L-14).
