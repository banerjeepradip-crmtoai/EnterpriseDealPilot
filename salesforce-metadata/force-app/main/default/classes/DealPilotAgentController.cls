/**
 * Apex bridge between the DealPilot Agent LWC (dropped on the Opportunity
 * record page) and the ADK orchestrator's REST API (web_app.py, wrapping
 * google.adk.cli.fast_api.get_fast_api_app — see infrastructure/README.md).
 *
 * Talks to the same /apps/.../sessions and /run endpoints the ADK dev UI
 * itself calls; the backend agent code (agents/orchestrator/agent.py)
 * doesn't need to know or care whether the caller is the dev UI or this
 * controller. Deal state shown in the LWC's status rail is read directly
 * from Opportunity/Quote via SOQL rather than parsed out of the agent's
 * chat transcript — the agent already writes those fields back through
 * mcp-services/salesforce when SALESFORCE_MODE=live, so the record itself
 * is the source of truth, not a guess at the conversation's structure.
 *
 * Endpoint is a Custom Metadata setting (DealPilot_Setting__mdt.Default),
 * not a Named Credential: this org's Metadata API rejects an
 * ExternalCredential with authenticationProtocol NoAuthentication
 * (confirmed live — "External Credentials don't support the
 * 'NoAuthentication' authentication protocol"), and the ADK backend has
 * no auth of its own to pair one with. A plain callout against a
 * Remote Site Setting-allow-listed host is the correct mechanism for a
 * genuinely public, unauthenticated endpoint. Repointing the backend
 * (e.g. to a local ngrok tunnel) means updating the DealPilot_Setting__mdt
 * Default record's Base_URL__c AND the DealPilot_Agent Remote Site
 * Setting's url to match — never an Apex change.
 */
public with sharing class DealPilotAgentController {
    private static final String APP_NAME = 'orchestrator';
    private static final Integer CALLOUT_TIMEOUT_MS = 120000;

    public class ChatMessage {
        @AuraEnabled
        public String author;
        @AuraEnabled
        public String text;

        public ChatMessage(String author, String text) {
            this.author = author;
            this.text = text;
        }
    }

    public class AgentTurnResult {
        @AuraEnabled
        public String sessionId;
        @AuraEnabled
        public List<ChatMessage> messages;
    }

    public class DealStatus {
        @AuraEnabled
        public String opportunityName;
        @AuraEnabled
        public String stageName;
        @AuraEnabled
        public Boolean budgetConfirmed;
        @AuraEnabled
        public String dataResidency;
        @AuraEnabled
        public String useCase;
        @AuraEnabled
        public String quoteName;
        @AuraEnabled
        public Decimal signedTotal;
        @AuraEnabled
        public Decimal discountPct;
        @AuraEnabled
        public String approvalStatus;
    }

    @AuraEnabled(cacheable=true)
    public static DealStatus getDealStatus(Id opportunityId) {
        List<Opportunity> opps = [
            SELECT Name, StageName, Budget_Confirmed__c, Use_Case__c, Account.Data_Residency__c
            FROM Opportunity
            WHERE Id = :opportunityId
            LIMIT 1
        ];
        if (opps.isEmpty()) {
            throw newAuraException('Opportunity not found: ' + opportunityId);
        }
        Opportunity opp = opps[0];

        DealStatus status = new DealStatus();
        status.opportunityName = opp.Name;
        status.stageName = opp.StageName;
        status.budgetConfirmed = opp.Budget_Confirmed__c == null
            ? null
            : opp.Budget_Confirmed__c == 'Yes';
        status.dataResidency = opp.Account != null ? opp.Account.Data_Residency__c : null;
        status.useCase = opp.Use_Case__c;

        List<Quote> quotes = [
            SELECT Name, Signed_Total__c, Discount_Pct__c, Approval_Status__c
            FROM Quote
            WHERE OpportunityId = :opportunityId
            ORDER BY CreatedDate DESC
            LIMIT 1
        ];
        if (!quotes.isEmpty()) {
            Quote q = quotes[0];
            status.quoteName = q.Name;
            status.signedTotal = q.Signed_Total__c;
            status.discountPct = q.Discount_Pct__c;
            status.approvalStatus = q.Approval_Status__c;
        }
        return status;
    }

    /**
     * Opens a new ADK session and immediately sends the Opportunity Id as
     * the first user turn — matches the orchestrator's own instruction
     * ("When a seller gives you an Opportunity Id..."), so the seller
     * never has to type or paste the Id themselves.
     */
    @AuraEnabled
    public static AgentTurnResult startConversation(Id opportunityId) {
        String sessionId = createSession();
        AgentTurnResult result = runTurn(sessionId, String.valueOf(opportunityId));
        result.sessionId = sessionId;
        return result;
    }

    @AuraEnabled
    public static AgentTurnResult sendMessage(String sessionId, String message) {
        if (String.isBlank(sessionId)) {
            throw newAuraException('No active DealPilot session — start a conversation first.');
        }
        return runTurn(sessionId, message);
    }

    private static String createSession() {
        HttpRequest req = new HttpRequest();
        req.setEndpoint(
            baseUrl() + '/apps/' + APP_NAME + '/users/' + currentUserId() + '/sessions'
        );
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setTimeout(CALLOUT_TIMEOUT_MS);
        req.setBody('{}');

        HttpResponse res = new Http().send(req);
        if (res.getStatusCode() >= 300) {
            throw newAuraException(
                'Could not start a DealPilot session (HTTP ' + res.getStatusCode() + ').'
            );
        }
        Map<String, Object> body = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
        return (String) body.get('id');
    }

    private static AgentTurnResult runTurn(String sessionId, String message) {
        Map<String, Object> newMessage = new Map<String, Object>{
            'role' => 'user',
            'parts' => new List<Object>{ new Map<String, Object>{ 'text' => message } }
        };
        Map<String, Object> payload = new Map<String, Object>{
            'app_name' => APP_NAME,
            'user_id' => currentUserId(),
            'session_id' => sessionId,
            'new_message' => newMessage
        };

        HttpRequest req = new HttpRequest();
        req.setEndpoint(baseUrl() + '/run');
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setTimeout(CALLOUT_TIMEOUT_MS);
        req.setBody(JSON.serialize(payload));

        HttpResponse res = new Http().send(req);
        if (res.getStatusCode() >= 300) {
            throw newAuraException(
                'DealPilot agent turn failed (HTTP ' + res.getStatusCode() + ').'
            );
        }

        AgentTurnResult result = new AgentTurnResult();
        result.sessionId = sessionId;
        result.messages = extractAssistantMessages(
            (List<Object>) JSON.deserializeUntyped(res.getBody())
        );
        return result;
    }

    /**
     * Pulls only the natural-language turns out of the ADK event stream.
     * Sub-agent delegation (solution_pricing_agent, risk_approval_agent,
     * proposal_communication_agent) happens via AgentTool function
     * calls/responses on the orchestrator's own event list — those events
     * carry structured functionCall/functionResponse parts, not a `text`
     * part, so they're skipped here rather than surfaced as raw tool JSON.
     * The orchestrator's own relayed summary (which it's instructed to
     * report faithfully — see agent.py) is what actually reaches the
     * seller, exactly as in the ADK dev UI's chat transcript.
     */
    private static List<ChatMessage> extractAssistantMessages(List<Object> events) {
        List<ChatMessage> messages = new List<ChatMessage>();
        for (Object eventObj : events) {
            Map<String, Object> event = (Map<String, Object>) eventObj;
            if (event.get('author') == 'user') {
                continue;
            }
            Map<String, Object> content = (Map<String, Object>) event.get('content');
            if (content == null || content.get('parts') == null) {
                continue;
            }
            String combinedText = '';
            for (Object partObj : (List<Object>) content.get('parts')) {
                Map<String, Object> part = (Map<String, Object>) partObj;
                if (part.get('text') != null) {
                    combinedText += (String) part.get('text');
                }
            }
            if (String.isNotBlank(combinedText)) {
                messages.add(new ChatMessage('DealPilot', combinedText));
            }
        }
        return messages;
    }

    private static String currentUserId() {
        return UserInfo.getUserId();
    }

    private static String baseUrl() {
        DealPilot_Setting__mdt setting = DealPilot_Setting__mdt.getInstance('Default');
        if (setting == null || String.isBlank(setting.Base_URL__c)) {
            throw newAuraException(
                'DealPilot_Setting__mdt.Default.Base_URL__c is not configured.'
            );
        }
        return setting.Base_URL__c;
    }

    private static AuraHandledException newAuraException(String message) {
        AuraHandledException ex = new AuraHandledException(message);
        ex.setMessage(message);
        return ex;
    }
}
