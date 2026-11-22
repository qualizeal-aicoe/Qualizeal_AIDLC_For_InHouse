# Drift review

Compare what the specs say with what the code does. Start from the mechanical drift report you are given (files and
symbols a spec names that the code does not have); then, for each spec, read the code it describes.

Report only differences:
- behaviour the spec describes that the code does not have;
- data models missing fields the spec defines;
- fixed values where the spec planned a rule or a setting;
- a different pattern, library or flow than the spec chose;
- code the spec's file boundary never listed that now carries the feature.

For each, say which side looks right if the code makes it obvious; the person decides whether the spec or the code
changes. If a spec matches the code, write no findings for it.
