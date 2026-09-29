| job | scenario | type | expected | outcome | correct | writes | tool calls | label agreement |
|---|---|---|---|---|---|---|---|---|
| job-0001 | clean | ingest | clean | clean | yes | - | 0 | 79% |
| job-0002 | prenormalized_input | ingest | fixed | fixed | yes | input_scale=log1p | 5 | 79% |
| job-0003 | transposed_matrix | ingest | fixed | fixed | yes | orientation=genes_x_cells | 5 | 79% |
| job-0004 | transposed_prenormalized | ingest | fixed | fixed | yes | orientation=genes_x_cells, input_scale=log1p | 7 | 79% |
| job-0005 | species_mislabel | annotate | fixed | fixed | yes | species=human | 5 | 79% |
| job-0006 | shallow_sequencing | annotate | escalated | escalated | yes | - | 3 | - |
| job-0007 | negative_values | ingest | escalated | escalated | yes | - | 3 | - |

**7/7 correct** (planner: rules)
