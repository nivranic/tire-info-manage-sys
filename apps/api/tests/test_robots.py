from tire_api.adapters.robots import RobotsPolicy

AGENT = "TireEvidenceResearch/0.1"


def test_manufacturer_wildcards_and_query_restrictions():
    policy = RobotsPolicy("""
User-agent: BadBot
Disallow: /
User-agent: *
Disallow: /api/
Disallow: /*sku=
Disallow: /*tyreSize=
Disallow: /*currentPage=
""", AGENT)
    assert policy.can_fetch("https://official.test/auto/tyres/model")
    assert not policy.can_fetch("https://official.test/api/product")
    assert not policy.can_fetch("https://official.test/auto/tyres/model?sku=123")
    assert not policy.can_fetch("https://official.test/auto/tyres/model?a=1&tyreSize=20")


def test_longest_match_allow_tie_and_end_anchor():
    policy = RobotsPolicy("User-agent: *\nDisallow: /specs/\nAllow: /specs/public/\nDisallow: /specs/public/private\nDisallow: /end$\nDisallow: /tie\nAllow: /tie", AGENT)
    assert not policy.can_fetch("https://official.test/specs/one")
    assert policy.can_fetch("https://official.test/specs/public/one")
    assert not policy.can_fetch("https://official.test/specs/public/private/one")
    assert not policy.can_fetch("https://official.test/end")
    assert policy.can_fetch("https://official.test/ending")
    assert policy.can_fetch("https://official.test/tie")


def test_specific_agent_and_duplicate_groups_merge():
    policy = RobotsPolicy("User-agent: *\nDisallow: /\nUser-agent: TireEvidence\nDisallow: /one\nUser-agent: TireEvidence\nDisallow: /two\nCrawl-delay: 3\nRequest-rate: 1/5", AGENT)
    assert policy.can_fetch("https://official.test/allowed")
    assert not policy.can_fetch("https://official.test/one")
    assert not policy.can_fetch("https://official.test/two")
    assert policy.minimum_interval == 5


def test_unreserved_encoding_and_unicode_paths():
    policy = RobotsPolicy("User-agent: *\nDisallow: /%61pi/\nDisallow: /轮胎/", AGENT)
    assert not policy.can_fetch("https://official.test/api/private")
    assert not policy.can_fetch("https://official.test/%E8%BD%AE%E8%83%8E/detail")


def test_consecutive_user_agents_and_empty_disallow():
    policy = RobotsPolicy("User-agent: TireEvidence\nUser-agent: AnotherBot\nDisallow:\nDisallow: /private # comment", AGENT)
    assert policy.can_fetch("https://official.test/public")
    assert not policy.can_fetch("https://official.test/private")
