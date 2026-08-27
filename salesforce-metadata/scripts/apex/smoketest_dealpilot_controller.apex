Id oppId = '006gK00000NMi6oQAD'; // Baltic Freight Group - New Business
DealPilotAgentController.AgentTurnResult result = DealPilotAgentController.startConversation(oppId);
System.debug('SESSION_ID: ' + result.sessionId);
System.debug('MESSAGE_COUNT: ' + result.messages.size());
for (DealPilotAgentController.ChatMessage m : result.messages) {
    System.debug('MSG[' + m.author + ']: ' + m.text.abbreviate(400));
}

DealPilotAgentController.DealStatus status = DealPilotAgentController.getDealStatus(oppId);
System.debug('STATUS budgetConfirmed=' + status.budgetConfirmed + ' dataResidency=' + status.dataResidency +
    ' quoteName=' + status.quoteName + ' signedTotal=' + status.signedTotal + ' approvalStatus=' + status.approvalStatus);
