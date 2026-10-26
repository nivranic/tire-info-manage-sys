# Professional test bridge corpus v1

This corpus supplies independently authored expectations for the professional
TestEvent-to-exact-SKU bridge and same-event candidate explanation. It does not
extend the existing tire/vehicle Parser Golden contract or authorize a release.

- `synthetic_contract`: project-authored engineering inputs and expectations.
- `real_source_unknown_or_inadmissible`: real material whose exact SKU has not
  been established; unknown is distinct from a false association.
- `real_source_human_reviewed`: an externally reviewed tier reserved for future
  evidence. A tier label, agent, two local accounts or a string signature does
  not authenticate a human reviewer. Current human qualification stays pending.

Expected fields are authored independently of product outputs. Input hashes and
the manifest bind the exact UTF-8 files; dynamic product UUIDs only bind the
captured product records. Original values, field presence, null, false, zero,
negative zero, namespaces, markets, source ranks and test conditions are not
interchangeable. Missing positive or distinct-pair coverage cannot establish
zero wrong merges. Engineering success and human Golden qualification are
reported separately.

Private HTTP execution obtains current R71 views and actual R75 POST responses.
Offline snapshot checking proves only agreement with those bound bytes, not
current database state, latest revisions, licensing, human identity or a live
execution. No model, provider use, material export, normal database startup or
new production migration is part of this corpus.

The R74 Frontiers article (Wilkinson et al., 2023, DOI
10.3389/fenvs.2023.1258922) is a real-source unknown example. It reports TRWP
experiments and nine commercial names/study codes, without establishing exact
SKU identity or a tested size suitable for the product EventPayload. Its sample
uses `source_review_only`; no size, event, bridge or performance measurement is
invented to make it runnable. Table 3's particle classification proportions are
not whole-tire wear rates or performance scores.

Attribution: Tim Wilkinson, Ida Järlskog, Juliana Aristéia de Lima, Mats
Gustafsson, Karin Mattsson, Yvonne Andersson Sköld and Martin Hassellöv,
Frontiers in Environmental Science 11:1258922, 7 November 2023. Article licence:
CC BY 4.0, https://creativecommons.org/licenses/by/4.0/. No endorsement is
implied. Figure 1 separately credits Mats Gustafsson/VTI and Mattsson et al.
(2023); the corpus does not copy that image, the full paper, or external works.
Only bounded metadata and short identifier references are included. Existing
`provider_use:false` and `export:false` restrictions remain.

The archived original, capture receipt and agent document-review bindings are
referenced by exact byte count/SHA outside this managed directory. They are not
bundled or silently replaced by a public URL; missing external evidence must be
reported. The corpus and its hashes are not a backup of those materials.
