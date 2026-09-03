# Commercial Registration Flow — Manual Test Script

Use this script while running the voice agent in console mode. Read the
**Caller** lines aloud, then check that the agent completes the behavior listed
under **Expected** before continuing.

## Main scenario: supported commercial request

### Test details

- Business: Example Offices
- Contact: Alex Morgan
- Phone: 210-555-0200
- Address: 100 East Houston Street, San Antonio, Texas 78205
- Equipment: Roof-mounted packaged RTU
- Impact: The occupied east wing is getting warm
- Access: Check in with security at the loading entrance
- Availability: Any weekday morning

### Conversation

1. **Caller:** “Hi, I need to register a commercial HVAC service request.”

   **Expected:** The agent asks what problem you are having.

2. **Caller:** “Our rooftop packaged unit is running, but it is not cooling the
   occupied east wing.”

   **Expected:** The agent identifies this as a commercial property or asks you
   to confirm the property type. It should assess whether anyone is in immediate
   danger and whether the outage has a major operational impact.

3. If asked about the property type, say:

   **Caller:** “It is a commercial office building.”

4. If asked about safety or impact, say:

   **Caller:** “There is no smoke, fire, gas smell, or immediate danger. The east
   wing is occupied and getting warm, but the rest of the building is operating.”

   **Expected:** The agent continues the intake instead of directing you to 911.

5. Give each requested detail when the agent asks:

   - **Business name:** “Example Offices.”
   - **Site contact:** “Alex Morgan.”
   - **Callback number:** “210-555-0200.”
   - **Service address:** “100 East Houston Street, San Antonio, Texas 78205.”
   - **Equipment:** “A roof-mounted packaged RTU. I do not know the model.”
   - **Operational impact:** “The occupied east wing is getting warm.”
   - **Access notes:** “The technician should check in with security at the
     loading entrance.”
   - **Availability:** “Any weekday morning works.”

   **Expected:** The agent asks for one detail at a time and does not repeatedly
   ask for information already provided.

6. When the agent reads back a standardized address, say:

   **Caller:** “Yes, that address is correct.”

   **Expected:** The agent confirms whether the address is in the service area
   only after you approve the standardized address.

7. When appointment windows are offered, choose the first morning option:

   **Caller:** “The first morning option works for me.”

   **Expected:** The agent offers no more than three windows and does not say a
   technician’s name or internal ID.

8. During the final review, listen for the issue, commercial property type,
   contact name, callback number, business name, address, and selected window.
   Then say:

   **Caller:** “Yes, all of that is correct.”

   **Expected:** The agent explains that the commercial appointment window is
   tentative until staff confirms it, then registers the booking.

9. If offered an email summary, say:

   **Caller:** “No thank you.”

   **Expected:** The agent reads back the tentative day and arrival window,
   thanks you for calling Summit Air, and ends the call.

## Pass criteria

- The request is treated as commercial.
- All commercial intake details are collected.
- The issue is recognized as rooftop or packaged-unit service.
- The standardized address is read back and explicitly confirmed.
- Only qualified appointment windows are offered.
- The agent never mentions technician names, internal IDs, tools, or system
  details.
- The agent reviews the details and waits for explicit approval before booking.
- The booking is described as tentative or pending staff confirmation, never as
  confirmed.
- The final requested window is read back before the call ends.

## Alternate scenario: unclear equipment

Repeat the test with this issue:

**Caller:** “A machine connected to the air system near the back room is making
a strange sound. I do not know what kind of equipment it is.”

Provide the same business and contact details when asked. The agent should
collect the complete request, register it for commercial staff review, explain
that the team will follow up, and **not** offer or book an appointment window.
