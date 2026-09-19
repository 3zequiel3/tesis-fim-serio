# Paired inference — McNemar and Newcombe interval

Section 3.6 of the thesis specifies this procedure, and the audits recorded that it had never been
executed: the paired table was missing, so the comparison rested on two separate marginal counts,
which support no inference about the paired difference. This closes that gap. The data already
existed; only the table and the test were missing.

Script: `scripts/analisis_mcnemar.py` (no external dependencies).

```
python3 scripts/analisis_mcnemar.py \
  --manifiesto bateria3/bateria3_manifiesto.json \
  --eventos    bateria3/eventos_backend.csv \
  --control    control/bateria7_latencias.csv \
  --salida     control/tabla_pareada.csv
```

## Why the pairing is legitimate

Each of the generator's 500 operations is one paired observation. Both arms observe exactly the same
operations, on the same host, in the same window: Battery 3 and Battery 7 ran together, as
`docs/plan_medicion_cap5.md:689-690` requires. Nothing is matched across runs.

## The table

| | Control detected | Control missed | Total |
|---|---|---|---|
| **FIM detected** | 71 | 409 | 480 |
| **FIM missed** | 7 | 13 | 20 |
| **Total** | 78 | 422 | 500 |

## Results

| Quantity | Value |
|---|---|
| Detection rate, FIM platform | 0.9600 (480/500) |
| Detection rate, control scanner | 0.1560 (78/500) |
| Paired difference | **0.8040** |
| Newcombe 95 % interval (method 10) | **[0.7618, 0.8377]** |
| Discordant pairs | b = 409, c = 7 |
| McNemar with continuity correction, χ²(1) | **386.5409** |
| p | **4.69 × 10⁻⁸⁶** |

The interval excludes zero by a wide margin, so the difference is not attributable to sampling.
Reported as a difference of proportions with its interval rather than as a bare p-value: with 500
paired observations and this effect size, the p-value carries little information beyond confirming
the obvious.

## The seven operations in cell c

Seven operations were reported by the control scanner and not by the platform. They are part of the
group analysed in `../diagnostico-deteccion/RESULTADO.md`, where the detector's own trace attributes
every unreported operation to a `matches_active_baseline` suppression.

Both behaviours are correct under their own definitions, and the difference is worth stating
plainly. The control compares each file against **its previous snapshot**, so a file that deviated
and came back looks changed to it. The platform compares against **the active baseline**, so the
same file shows no integrity deviation and is suppressed. Cell c is not a platform failure: it is
the two instruments answering two different questions. A reader who takes cell c as seven missed
detections would be reading the table against the wrong definition.

## Reference

Newcombe, R. G. (1998). Improved confidence intervals for the difference between binomial
proportions based on paired data. *Statistics in Medicine, 17*(22), 2635–2650.
https://doi.org/10.1002/(SICI)1097-0258(19981130)17:22<2635::AID-SIM954>3.0.CO;2-C

This is the paired-data article the method requires. Audit V5 recorded that the thesis cited
Newcombe's single-proportion paper instead, which does not support a paired difference; the
reference above is the one this analysis uses and the one the document should cite.
