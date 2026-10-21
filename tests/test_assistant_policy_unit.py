import unittest

from crm_api.services.assistant_policy import AssistantPolicy


ARTICLE = "CRM_REP_SEARCH_PRICE_ITEMS"
CUSTOMER = "GET_CURRENT_PRICE_LIST"


class AssistantPolicyTests(unittest.TestCase):
    def test_default_denies_everything(self):
        self.assertFalse(AssistantPolicy().allows(ARTICLE))

    def test_both_organization_and_representative_must_be_enabled(self):
        for organization, representative in ((False, False), (True, False), (False, True)):
            with self.subTest(organization=organization, representative=representative):
                policy = AssistantPolicy(organization, representative, frozenset({ARTICLE}))
                self.assertFalse(policy.allows(ARTICLE))

    def test_only_selected_actions_are_enabled(self):
        policy = AssistantPolicy(True, True, frozenset({ARTICLE}))
        self.assertTrue(policy.allows(ARTICLE))
        self.assertFalse(policy.allows("CRM_REP_LOOKUP_CUSTOMER"))
        self.assertFalse(policy.allows(CUSTOMER))

    def test_customer_and_unknown_actions_are_rejected(self):
        for capability in (CUSTOMER, "UNKNOWN"):
            with self.subTest(capability=capability), self.assertRaises(ValueError):
                AssistantPolicy(True, True, frozenset({capability}))


if __name__ == "__main__":
    unittest.main()
