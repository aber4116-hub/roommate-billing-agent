/** 应用状态；单页应用，数据量有限，直接持有可渲染状态。 */

export const state = {
  user: null,
  households: [],
  householdId: null,
  household: null,
  role: null,
  personId: null,
  periods: [],
  period: null,
  people: [],
  bills: [],
  occupancies: [],
  payments: [],
  preview: null,
  settlements: [],
  rules: [],
  members: [],
  invites: [],
  conversations: [],
  activeConversationId: null,
  messages: [],
  pendingActions: [],
  currentView: "overview",
  currentRule: null,
  ruleDraft: null,
  rulePreview: null,
  busy: false,
};

export function resetHouseholdState() {
  state.householdId = null;
  state.household = null;
  state.role = null;
  state.personId = null;
  state.periods = [];
  state.period = null;
  state.people = [];
  state.bills = [];
  state.occupancies = [];
  state.payments = [];
  state.preview = null;
  state.settlements = [];
  state.rules = [];
  state.members = [];
  state.invites = [];
  state.conversations = [];
  state.activeConversationId = null;
  state.messages = [];
  state.pendingActions = [];
  state.currentRule = null;
  state.ruleDraft = null;
  state.rulePreview = null;
}
