# Evidence / starting material (collected 2026-11-16 by Grok Bot)

All produced against the public 0 A.D. repository https://gitea.wildfiregames.com/0ad/0ad
(blobless clone, HEAD `14b258b10`, 2026-11-15).

| File | What it is |
|---|---|
| `dupcheck.sh` | Rule R1 (same texture basename in both .png and .dds). Reproduces issue #6738 at `eafacb6e2^`. |
| `rankcheck.py` | Rule R2 (expert `_e_` unit actor referencing an advanced/basic `_a_`/`_b_` unit prop). `python rankcheck.py 3142b7cba^` → 2 hits (kushites = issue #7649, persians = sibling); `python rankcheck.py HEAD` → 1 hit (`achaemenids/cavalry_javelinist_e_m.xml`, gather_meat variant, line ~47). Slow (git show per file, ~20 s). |
| `refcheck.py` | Rule R5 (reference integrity). 0 missing at HEAD over 69,123 refs. |
| `refcheck_head.json` | Output of the R5 check at HEAD (empty = no broken refs). |
| `art_issues.json` | Raw Gitea API dump of all 252 issues labelled `Theme/Art & Animation` (state=all), fetched 2026-11-16. |

These are prototypes: turn them into tested modules in the new repo, do not ship them as-is.

The original Issue snapshot may be copied here from the supplied research pack when needed. The tracked project fetches the Issue list from the official Gitea API by default.
