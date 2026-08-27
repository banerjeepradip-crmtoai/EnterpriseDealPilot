import { LightningElement, api } from "lwc";
import { ShowToastEvent } from "lightning/platformShowToastEvent";
import getDealStatus from "@salesforce/apex/DealPilotAgentController.getDealStatus";
import startConversation from "@salesforce/apex/DealPilotAgentController.startConversation";
import sendMessage from "@salesforce/apex/DealPilotAgentController.sendMessage";

/**
 * Chat front end for the Deal Orchestrator, embedded on the Opportunity
 * record page. Replaces driving the golden path through the ADK dev UI
 * (`adk web`) — the agent code and REST API underneath are unchanged, this
 * is a different caller of the same /run endpoint. The status rail reads
 * Opportunity/Quote fields directly via Apex/SOQL rather than parsing the
 * agent's chat transcript, so it stays accurate even if the agent's wording
 * changes.
 */
export default class DealPilotAgent extends LightningElement {
    @api recordId;

    started = false;
    loading = false;
    draft = "";
    sessionId;
    messages = [];
    status = {};
    _seq = 0;

    connectedCallback() {
        this.refreshStatus();
    }

    get startDisabled() {
        return this.loading || this.started;
    }

    get sendDisabled() {
        return this.loading || !this.draft || !this.started;
    }

    get budgetConfirmedLabel() {
        if (this.status.budgetConfirmed === true) {
            return "Confirmed";
        }
        if (this.status.budgetConfirmed === false) {
            return "Declined";
        }
        return "Not yet confirmed";
    }

    get dataResidencyLabel() {
        return this.status.dataResidency || "Not yet confirmed";
    }

    get quoteLabel() {
        return this.status.quoteName || "No quote yet";
    }

    get signedTotalLabel() {
        return this.status.signedTotal != null
            ? this.formatCurrency(this.status.signedTotal)
            : "—";
    }

    get approvalStatusLabel() {
        return this.status.approvalStatus || "—";
    }

    get approvalBadgeClass() {
        const base = "slds-badge dp-badge";
        const themeByStatus = {
            Pending: "slds-theme_warning",
            Approved: "slds-theme_success",
            Rejected: "slds-theme_error"
        };
        const theme = themeByStatus[this.status.approvalStatus];
        return theme ? `${base} ${theme}` : base;
    }

    async refreshStatus() {
        try {
            this.status = await getDealStatus({ opportunityId: this.recordId });
        } catch (error) {
            // A brand-new Opportunity with no Quote yet is expected to come
            // back mostly empty, not an error worth interrupting the seller
            // over — the chat is still fully usable without this rail.
        }
    }

    async handleStart() {
        this.loading = true;
        try {
            const result = await startConversation({ opportunityId: this.recordId });
            this.sessionId = result.sessionId;
            this.started = true;
            this.appendAssistantMessages(result.messages);
            await this.refreshStatus();
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.loading = false;
        }
    }

    handleDraftChange(event) {
        this.draft = event.target.value;
    }

    handleKeyUp(event) {
        if (event.key === "Enter" && !this.sendDisabled) {
            this.handleSend();
        }
    }

    async handleSend() {
        const text = this.draft.trim();
        if (!text) {
            return;
        }
        this.messages = [...this.messages, this.toDisplayMessage(text, "You", true)];
        this.draft = "";
        this.loading = true;
        try {
            const result = await sendMessage({ sessionId: this.sessionId, message: text });
            this.appendAssistantMessages(result.messages);
            await this.refreshStatus();
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.loading = false;
        }
    }

    appendAssistantMessages(newMessages) {
        const mapped = (newMessages || []).map((message) =>
            this.toDisplayMessage(message.text, "DealPilot", false)
        );
        this.messages = [...this.messages, ...mapped];
    }

    toDisplayMessage(text, author, isUser) {
        this._seq += 1;
        return {
            id: this._seq,
            text,
            author,
            listItemClass: isUser
                ? "slds-chat-listitem slds-chat-listitem_outbound"
                : "slds-chat-listitem slds-chat-listitem_inbound",
            textClass: isUser
                ? "slds-chat-message__text slds-chat-message__text_outbound"
                : "slds-chat-message__text slds-chat-message__text_inbound"
        };
    }

    formatCurrency(value) {
        try {
            return new Intl.NumberFormat(undefined, {
                style: "currency",
                currency: "USD"
            }).format(value);
        } catch (error) {
            return String(value);
        }
    }

    notifyError(error) {
        const message =
            (error && error.body && error.body.message) ||
            "Something went wrong talking to DealPilot.";
        this.dispatchEvent(
            new ShowToastEvent({
                title: "DealPilot error",
                message,
                variant: "error"
            })
        );
    }
}
