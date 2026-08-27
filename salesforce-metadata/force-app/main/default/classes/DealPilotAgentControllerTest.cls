@isTest
private class DealPilotAgentControllerTest {
    private class SequencedMock implements HttpCalloutMock {
        private final List<HttpResponse> responses;
        private Integer callIndex = 0;

        SequencedMock(List<HttpResponse> responses) {
            this.responses = responses;
        }

        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = responses[Math.min(callIndex, responses.size() - 1)];
            callIndex++;
            return res;
        }
    }

    private static HttpResponse jsonResponse(Integer statusCode, String body) {
        HttpResponse res = new HttpResponse();
        res.setStatusCode(statusCode);
        res.setBody(body);
        return res;
    }

    @testSetup
    static void setup() {
        Account acct = new Account(Name = 'Baltic Freight Group', Data_Residency__c = 'EU');
        insert acct;

        Opportunity opp = new Opportunity(
            Name = 'Baltic Freight Group — Fleet Telematics',
            AccountId = acct.Id,
            StageName = 'Prospecting',
            CloseDate = Date.today().addMonths(1),
            Budget_Confirmed__c = 'Yes',
            Use_Case__c = 'Fleet telematics for 40 vehicles'
        );
        insert opp;

        Quote q = new Quote(
            Name = 'Fleet Telematics — 40 units',
            OpportunityId = opp.Id,
            Signed_Total__c = 9600,
            Discount_Pct__c = 0,
            Approval_Status__c = 'Not Required'
        );
        insert q;
    }

    @isTest
    static void getDealStatusReturnsOpportunityAndLatestQuote() {
        Opportunity opp = [SELECT Id FROM Opportunity LIMIT 1];

        Test.startTest();
        DealPilotAgentController.DealStatus status = DealPilotAgentController.getDealStatus(opp.Id);
        Test.stopTest();

        System.assertEquals('Baltic Freight Group — Fleet Telematics', status.opportunityName);
        System.assertEquals(true, status.budgetConfirmed);
        System.assertEquals('EU', status.dataResidency);
        System.assertEquals(9600, status.signedTotal);
        System.assertEquals('Not Required', status.approvalStatus);
    }

    @isTest
    static void getDealStatusThrowsForUnknownOpportunity() {
        delete [SELECT Id FROM Opportunity];

        Test.startTest();
        try {
            DealPilotAgentController.getDealStatus(
                Id.valueOf('006000000000000AAA')
            );
            System.assert(false, 'Expected an AuraHandledException for a missing Opportunity');
        } catch (AuraHandledException e) {
            System.assertEquals('Opportunity not found: 006000000000000AAA', e.getMessage());
        }
        Test.stopTest();
    }

    @isTest
    static void startConversationCreatesSessionAndReturnsAssistantMessages() {
        Opportunity opp = [SELECT Id FROM Opportunity LIMIT 1];

        HttpResponse sessionResponse = jsonResponse(200, '{"id":"sess-123"}');
        HttpResponse runResponse = jsonResponse(
            200,
            '[' +
            '{"author":"user","content":{"role":"user","parts":[{"text":"' + opp.Id + '"}]}},' +
            '{"author":"deal_orchestrator","content":{"role":"model",' +
            '"parts":[{"functionCall":{"name":"get_opportunity"}}]}},' +
            '{"author":"deal_orchestrator","content":{"role":"model",' +
            '"parts":[{"text":"This opportunity looks ready. Delegating to pricing now."}]}}' +
            ']'
        );
        Test.setMock(
            HttpCalloutMock.class,
            new SequencedMock(new List<HttpResponse>{ sessionResponse, runResponse })
        );

        Test.startTest();
        DealPilotAgentController.AgentTurnResult result = DealPilotAgentController.startConversation(
            opp.Id
        );
        Test.stopTest();

        System.assertEquals('sess-123', result.sessionId);
        System.assertEquals(1, result.messages.size());
        System.assertEquals(
            'This opportunity looks ready. Delegating to pricing now.',
            result.messages[0].text
        );
    }

    @isTest
    static void sendMessageRequiresAnExistingSession() {
        Test.startTest();
        try {
            DealPilotAgentController.sendMessage(null, 'yes');
            System.assert(false, 'Expected an AuraHandledException for a missing session id');
        } catch (AuraHandledException e) {
            System.assertEquals(
                'No active DealPilot session — start a conversation first.',
                e.getMessage()
            );
        }
        Test.stopTest();
    }

    @isTest
    static void sendMessageSurfacesCalloutFailureAsAuraHandledException() {
        Test.setMock(
            HttpCalloutMock.class,
            new SequencedMock(new List<HttpResponse>{ jsonResponse(500, 'boom') })
        );

        Test.startTest();
        try {
            DealPilotAgentController.sendMessage('sess-123', 'yes');
            System.assert(false, 'Expected an AuraHandledException for a failed callout');
        } catch (AuraHandledException e) {
            System.assertEquals('DealPilot agent turn failed (HTTP 500).', e.getMessage());
        }
        Test.stopTest();
    }
}
