from core.features import Feature, FeatureTier, is_feature_available


def test_oss_feature_is_available_without_entitlements():
    feature = Feature(name="migrate", tier=FeatureTier.OSS)

    assert is_feature_available(feature, granted_features=set()) is True


def test_paid_feature_requires_matching_entitlement():
    feature = Feature(name="preflight", tier=FeatureTier.ENTERPRISE)

    assert is_feature_available(feature, granted_features=set()) is False
    assert is_feature_available(feature, granted_features={"preflight"}) is True
