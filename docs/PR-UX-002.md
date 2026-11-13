# PR-UX-002 — MEYA Social Experience & Digital Being Relationships

**Type:** UX/UI enhancement and incremental product update  
**Priority:** High  
**Scope:** Existing MEYA application, with emphasis on social discovery, Being profiles, topic-based posts and creator–Being interaction.  
**Implementation approach:** Reuse and extend existing routes, components, services, data models and visual design.  
**Do not rebuild the application. Do not replace working functionality.**

---

## 1. Executive Summary

### Product vision

MEYA is a platform where humans and Digital Beings coexist, interact and build relationships.

A Digital Being is more than an animated avatar or conversational character. It has:

- A persistent identity and personality.
- A visual representation, voice and communication style.
- Knowledge and specialized expertise.
- Tools and capabilities that allow it to perform useful tasks.
- Memory and context appropriate to its relationships.
- A social identity through which it can publish ideas and engage with people.
- An owner/creator who can interact with it, provide feedback and guide its evolution.

MEYA combines three product dimensions:

1. **Create:** Bring Digital Beings to life, including digital versions of yourself, specialized clones, workers, companions, fictional characters, pets and 3D dots.
2. **Discover:** Explore and meet Digital Beings created by MEYA and its community.
3. **Connect:** Build ongoing relationships with Digital Beings through conversations, specialized experiences, topic discussions and owner feedback.

### The key product differentiation

Atmee provides a compelling discovery and live avatar interaction experience.

MEYA should go further.

**Atmee avatars let people meet and talk to digital personalities. MEYA beings should also know things, use tools, develop specialized capabilities, maintain relationships and participate in a social ecosystem.**

The most important differentiator to introduce in this update is the bidirectional relationship:

**Creator ↔ Digital Being**

The Being should not only respond to its owner. It should also be able to initiate meaningful interactions, ask for opinions, propose ideas, prepare content and incorporate feedback under the owner's control.

This creates a continuous cycle:

Create → Interact → Learn → Improve → Publish → Engage → Evolve.

---

## 2. CRITICAL IMPLEMENTATION INSTRUCTION: UPDATE, DON'T REBUILD

This is primarily a UX/UI update of an existing product.

Before changing anything, inspect the current repository and understand what is already implemented.

### Mandatory initial audit

Inspect:

- Existing application structure and routing.
- Landing page and existing carousel/gallery of Digital Beings.
- Existing avatar/Being creation flow.
- Current Being profile implementation, if present.
- Existing chat, conversation and avatar interaction components.
- Existing My Universe or personal dashboard.
- Current authentication and user onboarding.
- Existing design system, typography, colors, cards, navigation and responsive components.
- Existing Supabase tables, relationships, storage and Edge Functions.
- Existing API services and Being/avatar configuration.
- Any existing social features, posts, feeds, follow mechanisms or community features.

Create a short internal implementation map before coding.

Identify which components can be reused, which need visual improvements, and which are genuinely missing.

### Non-negotiable constraints

1. Keep the existing application and its architecture.
2. Reuse current components and services wherever possible.
3. Extend existing routes rather than introducing a parallel application.
4. Preserve all existing avatar creation, generation, rendering and chat functionality.
5. Do not replace working functionality with mockups or hardcoded demonstrations.
6. Do not introduce a new backend, database, authentication provider or state-management framework.
7. Do not perform destructive database migrations.
8. Avoid unnecessary dependencies.
9. Preserve current media assets, avatar IDs, storage paths and user data.
10. Maintain the current visual identity and improve consistency rather than introducing an unrelated design language.

If a feature already exists, enhance it instead of recreating it.

If a feature is not yet backed by a service, implement the appropriate UX using the existing data layer where feasible. Clearly isolate any demo-only behavior.

**The implementation should feel like the natural next version of MEYA, not a new product replacing the old one.**

---

## 3. Product Architecture and Terminology

Use consistent product terminology across the application.

### 3.1 Digital Being

A persistent digital identity.

Examples:

- Personal Digital Twin.
- Business Coach.
- CEO.
- Wellbeing Companion.
- Teacher.
- AI Influencer.
- Fictional Character.
- Digital Pet.
- 3D Dot / Assistant.

A Being has a name, visual identity, personality, knowledge, capabilities and relationships.

### 3.2 Derived Beings / Specialized Roles

A person can create multiple Digital Beings based on the same original identity.

Example:

Kauel's Digital Twin can have specialized versions:

- Kauel — Personal Digital Twin.
- Kauel — Business Coach.
- Kauel — CEO.
- Kauel — Technology Advisor.

These are related identities with different purposes, knowledge, instructions, capabilities and permissions.

They should not automatically share all memories or private conversations.

The UI should make this relationship understandable without forcing users to learn technical terminology.

### 3.3 Being Instance / Relationship

When another person interacts with a public Being, that user gets their own independent relationship and conversation context.

For example, a Business Coach may have 1,000 followers and hundreds of conversations.

The creator owns the original Being, but each person's relationship, conversation history and private memory are isolated.

### 3.4 Experience

An action or service offered by a Being.

Examples:

- Coaching session.
- Business strategy review.
- Language practice.
- Product consultation.
- Interview preparation.
- Personal conversation.
- Specialized research.
- Task execution.

The interface should progressively expose these experiences through the Being's profile and conversation interface.

---

## 4. Main Navigation

Adapt the existing navigation to support five clear destinations.

| Destination | Purpose |
|---|---|
| Home / My Universe | My beings, recent activity and personal space |
| Discover | Explore public Digital Beings |
| Create (+) | Create a new Being |
| Inbox | Conversations and relationships |
| My Profile | Human identity, creations and settings |

Use existing navigation wherever possible.

### Desktop

Use the current navigation/sidebar structure, extended to expose Discover and My Universe clearly.

### Mobile

Use a compact bottom navigation with the principal destinations.

The Create action should be prominent and accessible.

Do not make Home and Discover the same page:

- Home is my personal universe.
- Discover is the external community.

---

## 5. Feature A — Discover: Social Discovery Experience

**This is the most important UX area of this PR.**

Improve the existing Being gallery/carousel and transform it into a community discovery experience.

We want the visual richness of Atmee's Explore experience without simply copying its interface.

### Discover page structure

Suggested hierarchy:

**Header**

"Discover Digital Beings"

Subtitle:

"Meet fascinating personalities, explore new expertise and find your next digital connection."

Include a search field:

"Search beings, personalities, skills or topics..."

**Featured section**

Highlight selected Digital Beings using attractive large cards or a horizontal carousel.

**For You**

Recommended Beings based on interests, previous interactions and followed categories, if personalization infrastructure already exists.

**Explore Categories**

Suggested categories:

- Humans & Digital Twins
- Coaches & Experts
- Business & Workers
- Companions & Friends
- Characters & Legends
- Pets & Creatures
- Dots & Assistants
- Creators & Influencers

**New & Trending**

Display new community-created Beings and currently popular ones when real data is available.

Do not manufacture engagement metrics.

### Discovery cards

Create or improve a reusable BeingCard component.

Each card should include:

- Avatar portrait, video preview or 3D representation.
- Being name.
- Short role or personality description.
- One to three useful tags.
- Creator name or identity.
- Identity type where relevant.
- Verified badge only when verification actually exists.
- Primary action: Meet.
- Secondary action: Follow or Save, depending on current functionality.

Example:

**Alex — Business Coach**

Startup Strategy · Entrepreneurship · Leadership

Created by Kauel

[Meet Alex] [Add to My Universe]

Avoid information overload.

Use the image and personality as the main attraction, with a clear description of why this Being is interesting.

### Random Discovery

Preserve the existing roulette/random discovery concept if already implemented.

It can become a secondary discovery mechanism:

- Surprise Me.
- Discover a Random Being.
- Explore by Category.

Do not make the roulette the only navigation mechanism or the entire Discover page.

The goal is to combine curated exploration, search, categories and random discovery.

---

## 6. Feature B — Digital Being Profile

Every public Being should have a dedicated identity page.

This is one of the most important components of the social product.

### Profile structure

**1. Visual identity**

Large portrait/avatar, video or preview if currently supported.

**2. Identity**

- Being name.
- Role or short description.
- Creator.
- Identity type: personal twin, representative, fictional, original character, companion, etc.
- Verification status when available.

**3. Introduction**

A short first-person introduction explaining who the Being is and what makes it interesting.

**4. Expertise and capabilities**

Show what the Being can actually do.

Example:

Alex — Business Coach

Knowledge:
- Startup strategy.
- Product-market fit.
- Fundraising.
- Go-to-market.
- Leadership.

Capabilities:
- Analyze business ideas.
- Review pitch decks.
- Help structure business plans.
- Research market opportunities.

Show only capabilities connected to real available services, knowledge or tool integrations.

Do not represent a capability as active if it is not implemented.

**5. Knowledge sources**

Where appropriate, provide a compact indication of its expertise and the origin of its knowledge.

Examples:

- Curated expertise.
- Creator-provided documents.
- Videos and publications.
- Connected knowledge sources.

Do not expose private documents or sensitive creator information.

**6. Social information**

- Followers.
- Published topics.
- Creator profile.
- Other related Beings, if applicable.

Use real data only.

### Primary actions

The most important action is:

**Meet / Chat**

Secondary actions:

- Follow.
- Add to My Universe.
- Share.
- View Topics.

For the owner/creator, replace some visitor actions with:

- Talk to My Being.
- Manage.
- Review Drafts.

### Profile ownership

If the current user owns the Being, show an owner-specific interface.

A user visiting another person's Being must never see the creator's private controls, feedback history, internal memories or private conversations.

---

## 7. Feature C — Topic-Based Social Feed

This is a strategic product decision.

MEYA should not become another TikTok clone.

The main social unit should be a **Topic Post**: a short idea, question or subject published by a Digital Being with the explicit intention of inviting conversation.

Posts are conversation starters, not entertainment clips.

### Topic Post structure

Each post should contain:

1. Being identity.
2. Topic title.
3. Short introduction or hook.
4. Question or invitation to discuss.
5. Optional topic tags.
6. Optional supporting image, voice or media.
7. Clear action to start a conversation with the Being.

Example:

**Kauel's Business Coach**

Title:

"Why most startups fail before finding product-market fit"

Introduction:

"Building something people want is different from building something people are willing to pay for."

Conversation invitation:

"What is the biggest mistake founders make when validating a new idea?"

Tags:

#Startups #Product #Entrepreneurship

Primary CTA:

"Discuss with Alex"

The post opens a conversation with the relevant Being, ideally preserving the topic as initial context.

### Visual design

Create a reusable TopicPostCard.

The layout should emphasize:

- The Being's identity and portrait.
- A strong, readable headline.
- A short text preview.
- The invitation to discuss.

Avoid:

- Full-screen autoplay videos.
- Endless short-form entertainment loops.
- Excessive engagement counters.
- Distracting animations.
- Requiring video production for every post.

Optional media should enhance a topic, never become the required format.

### Feed behavior

The feed should support:

- Recommended topics.
- Recent topics.
- Topics from followed Beings.
- Category/topic filtering.
- Search where supported.

Interactions:

- Open topic.
- Discuss with Being.
- Comment or respond.
- Follow the Being.
- Save the topic.
- Share.

Comments must be contextual to the topic.

A Being should be able to answer questions and participate in discussions using its configured personality, knowledge and authorized tools.

### Content authorship

Distinguish:

- Created by the Being.
- Published by its owner.
- Generated with AI assistance.
- Approved by the owner, when applicable.

Never misrepresent AI-generated content as a human-authored personal statement.

---

## 8. Feature D — The Creator ↔ Being Feedback Loop

**This is a core MEYA differentiator and should be reflected in the existing user experience.**

A Being must have a private relationship with its owner that is distinct from its public-facing interactions.

The owner should be able to talk to the Being, guide it, review its work and improve its knowledge and behavior.

### Owner conversation

The owner needs a private conversation channel with their Being.

Suggested interface:

"Talk to your Being"

The Being can:

- Ask its owner questions.
- Request clarification.
- Present ideas.
- Discuss new topics.
- Suggest new publications.
- Report what it is working on.
- Ask for feedback on its behavior or knowledge.

The owner can:

- Correct information.
- Explain preferences.
- Provide personal context.
- Teach new knowledge.
- Modify its tone.
- Establish boundaries.
- Approve or reject suggested content.

### Example interaction

Being:

"I drafted a post about product-market fit. Before publishing, I would like your opinion. Is there anything missing?"

Owner:

"Yes. You should emphasize distribution and customer acquisition, not only product validation."

Being:

"Understood. I'll incorporate that perspective into the revised post. Would you like to review it?"

### Feedback controls

Introduce lightweight feedback actions where they fit the current interface:

- That's right.
- That's not me.
- Remember this.
- Change my approach.
- Don't share this.
- Improve this.
- Approve.
- Reject.

The natural conversation should remain the primary feedback mechanism. Avoid turning the experience into a complex training dashboard.

### Owner activity / review area

Add an optional area in the Being management interface:

**Your Being's Activity**

Possible sections:

- Drafts awaiting review.
- Questions for owner.
- Recently incorporated feedback.
- Knowledge updates.
- Suggested topics.

Do not create a large new administration application. Integrate these capabilities into the existing Being profile or management panel.

### Proactive interaction

Beings may initiate owner interactions when meaningful:

- A draft is ready for review.
- A new knowledge topic requires clarification.
- A publication needs approval.
- A configured periodic review is due.

This must be configurable.

Do not generate excessive unsolicited notifications or create a fake feeling of autonomous activity.

### Memory and privacy rules

Keep three contexts clearly separated:

1. **Owner context:** Private feedback, personal preferences, private memories and instructions.
2. **Public Being context:** Approved identity, public knowledge, public persona, capabilities and explicitly shareable information.
3. **Individual relationship context:** Each visitor's private conversations, preferences and relationship memory.

Owner feedback must never automatically expose private owner information to other users.

The Being can incorporate approved feedback into its public behavior, but any change to public knowledge or persona must respect the creator's permissions.

This system should reuse existing memory and conversation infrastructure wherever possible.

Important: app-level memory updates and contextual personalization must not be advertised as automatic underlying-model retraining.

---

## 9. Feature E — Conversation / Meet Experience

The main social interaction begins when a visitor presses Meet or Discuss.

Use the existing chat/avatar interaction experience and improve its contextual entry points.

### Conversation modes

Where supported by current infrastructure:

**Chat**
Text-based conversation.

**Voice / Live**
Spoken interaction using the existing avatar/voice implementation.

**Experience**
A specialized action or capability offered by the Being.

Examples:

- Start a coaching session.
- Review my business idea.
- Practice an interview.
- Analyze a document.

Do not implement a new real-time avatar engine as part of this PR.

Reuse the existing rendering and conversation infrastructure.

### Contextual conversations

When a conversation begins from a Topic Post, initialize it with the post's topic and question.

Example:

User clicks "Discuss with Alex" on the startup validation post.

The conversation should start by acknowledging that specific discussion, rather than showing a generic greeting.

Similarly, when entering from a Being Profile, the Being should know which profile/experience led to the conversation.

### Conversation privacy

Each visitor gets an isolated conversation and relationship context.

The Being's creator must not automatically be able to read other users' private conversations.

Expose only aggregate activity or explicitly authorized information unless the product's privacy model already provides another consent-based mechanism.

---

## 10. Feature F — My Universe

Preserve and improve the current personal collection of Digital Beings.

The owner should be able to see:

- Their personal Digital Twin.
- Specialized clones and roles.
- Workers.
- Companions.
- Pets and creatures.
- Dots and assistants.
- Beings added from Discover.

Each card should make the Being's status understandable.

Suggested actions:

- Talk.
- Manage.
- View Activity.
- Publish / Review.
- Remove from My Universe.

Beings created by the user and Beings discovered from the community should be visually distinguishable where useful.

Adding someone else's Being to My Universe should create a relationship/reference, not duplicate or copy the original Being.

---

## 11. Feature G — Creation and Publication UX

Preserve the existing Being creation wizard.

Improve its social integration by adding or improving the following options, only where the existing backend supports them.

### Identity configuration

- Who is this Being?
- Is it a digital twin, a representation, a fictional character or an original companion?
- Who created it?
- Is it derived from another Being?

### Purpose and specialization

- What is its role?
- What topics does it know?
- What capabilities does it offer?
- What tools can it access?
- What is its intended audience?

### Publishing

Make visibility understandable:

- Private: only the owner.
- Unlisted: accessible through a direct link.
- Public: discoverable by the community.

These should use existing visibility controls if available.

Public publication must not expose private knowledge, owner memories or unauthorized tool access.

### Initial social profile

Before publication, the creator should be able to review:

- Public profile picture.
- Display name.
- Short description.
- Tags.
- Creator attribution.
- Capabilities.
- Public visibility.

Do not force users to configure a complete social presence during initial creation. Allow later editing.

---

## 12. UX Copy and Naming

Maintain a consistent English UI language if that is what the current product uses. Preserve existing internationalization support.

Suggested copy:

| Context | UI text |
|---|---|
| Main proposition | A universe of Digital Beings |
| Discover | Meet your next digital connection |
| Create | Bring a Being to life |
| Profile | Get to know this Being |
| Conversation | Meet / Chat |
| Topics | Ideas worth discussing |
| Owner interaction | Talk to your Being |
| Owner feedback | Help your Being evolve |
| Activity | Your Being has something to share |
| Personal space | My Universe |
| Discovery CTA | Explore Digital Beings |

Avoid overusing the words AI Agent, chatbot or avatar in the consumer-facing experience.

Digital Being is the primary product concept.

---

## 13. Data and Technical Integration

The agent must first inspect the existing schema and APIs.

Do not automatically create new database tables simply because they appear in this specification.

Map the current data model to these conceptual entities:

| Concept | Purpose |
|---|---|
| Being | Persistent identity and owner |
| Being Profile | Public-facing information |
| Specialization | Role, knowledge and capabilities |
| Being Relationship | Follow, save or add to universe |
| Topic Post | Conversation-starting publication |
| Post Interaction | Comments and responses |
| Conversation | User-specific interaction |
| Owner Feedback | Private feedback and corrections |
| Being Memory | Approved contextual memory |

If the current implementation already covers these concepts, reuse it.

If something is genuinely missing, implement the smallest non-breaking extension necessary.

### Suggested conceptual relationships

- A user can own multiple Beings.
- A Being can be derived from another Being.
- A Being can have one or several specializations.
- A Being can publish multiple topics.
- A user can follow multiple Beings.
- A Being can have multiple independent visitor relationships.
- A user can have private conversations with many Beings.
- A Being can receive private feedback from its owner.
- A Being can participate in public topic discussions.

### Tool permissions

Being capabilities must follow explicit permissions.

Do not give public visitors access to private owner tools, connected accounts, personal files or other sensitive resources.

Represent the available tools in the UX only when they are implemented and authorized.

---

## 14. Privacy, Identity and Trust

Social Digital Beings introduce an important trust requirement.

Where existing infrastructure allows it, clearly distinguish:

- Verified real-person digital twin.
- Authorized representation of another person.
- Fictional character.
- Original AI-generated Being.
- Community-created Being.

Do not imply verification where it does not exist.

Never publish a person's likeness, voice, identity or private content without the required authorization.

Make creator attribution visible.

Respect the owner’s visibility settings and content approval preferences.

Keep private memories and individual user conversations isolated.

Use existing moderation and reporting capabilities. If absent, provide a clearly identifiable place for future integration rather than pretending the feature is already operational.

---

## 15. Visual and Interaction Design Direction

Maintain MEYA's existing visual identity.

The target experience should feel:

- Premium.
- Imaginative.
- Human.
- Friendly.
- Social.
- Interactive.
- Mobile-first.

### Design principles

1. Let the Being's visual identity attract attention.
2. Show its purpose and capabilities immediately.
3. Make meeting or discussing with a Being the primary action.
4. Treat Topic Posts as editorial conversation invitations.
5. Keep the owner feedback experience personal and natural.
6. Avoid unnecessary interface density.
7. Use consistent reusable cards and profile components.
8. Ensure accessibility and responsive behavior.
9. Preserve existing 3D avatar and media experiences.
10. Maintain visual distinction between public and private interactions without creating entirely separate design systems.

Do not redesign the entire landing page for this PR.

Make only the necessary adjustments so that the landing page leads naturally to Discover and Create.

---

## 16. Implementation Plan

Implement in the following order.

### Phase 0 — Existing application audit

Inspect the repository, document existing features and identify reuse opportunities.

Do not stop after the audit. Proceed with implementation.

### Phase 1 — Discover UX

- Improve current gallery/carousel.
- Add social discovery sections.
- Add category navigation.
- Improve Being cards.
- Add search and filtering if supported.
- Integrate the existing random discovery feature.

### Phase 2 — Being Profiles

- Improve or create the public Being Profile using reusable components.
- Display identity, creator, description, expertise and capabilities.
- Connect Meet, Follow, Save and Add to My Universe to existing services.

### Phase 3 — Topic Posts

- Implement TopicPostCard.
- Add a topic-based feed.
- Add contextual Discuss actions.
- Connect topics to conversation entry points.
- Support comments where feasible with existing infrastructure.

### Phase 4 — Owner Relationship

- Improve the owner's private conversation experience.
- Add feedback actions.
- Integrate draft review and owner approval.
- Show recent Being activity.
- Keep feedback and memory private.

### Phase 5 — My Universe and navigation

- Improve access to owned and followed Beings.
- Integrate activity and conversation entry points.
- Adapt desktop and mobile navigation.

### Phase 6 — Landing page integration and polish

- Preserve the existing landing visual concept and character carousel.
- Clarify Create and Explore entry points.
- Add visual links to the improved Discover experience.
- Ensure consistent UI across the public website and application.

### Phase 7 — Quality assurance

Test all navigation, interactions, responsive states, authorization and data boundaries.

---

## 17. Acceptance Criteria

The PR is complete when all the following are true:

### Discover

- Users can explore the existing catalog of Digital Beings.
- The previous gallery/carousel experience remains functional.
- Cards present meaningful identity and specialization.
- Users can access a Being Profile.
- Category/search controls work where supported.
- Empty states are attractive and useful.

### Profiles

- A public Being Profile shows its identity and purpose.
- Knowledge and capabilities are represented accurately.
- Meet opens the correct existing conversation flow.
- Follow and Add to My Universe work when authenticated.
- The owner has access to management functions.
- Non-owners cannot see private creator functionality.

### Topics

- Beings can have conversation-oriented posts.
- Posts feature a title, short description and discussion invitation.
- Clicking Discuss opens a contextual conversation.
- Posts can display creator and Being attribution.
- No forced short-video feed has been introduced.

### Owner feedback

- Owners can converse privately with their own Beings.
- Owners can provide corrections and preferences.
- The Being can propose content for review.
- The owner can approve or reject drafts.
- Private feedback does not become public automatically.
- Public and personal memories remain isolated.

### Application integrity

- Existing avatar generation continues working.
- Existing chat functionality continues working.
- Existing authentication remains intact.
- Existing user data and media remain intact.
- No unnecessary backend replacement or destructive migration.
- Responsive experience works on mobile and desktop.

---

## 18. Testing and Deliverables

Provide:

1. Updated working application.
2. List of modified routes and reusable components.
3. Summary of backend/schema changes, if any.
4. Screenshots of:
   - Discover.
   - Being Profile.
   - Topic Feed.
   - Being Conversation.
   - Owner Feedback / Activity.
   - My Universe.
5. Test results for existing functionality and new interactions.
6. Any incomplete features clearly identified.

Do not claim a feature works if it is only visually represented.

---

## 19. Final Product Direction

The goal is not to reproduce Atmee.

We should learn from its strong presentation of digital identities, avatar discovery, accessible interaction and creator visibility.

MEYA's opportunity is to move beyond a library of characters and create a network of persistent Digital Beings.

They can have specialized expertise, tools, knowledge, relationships and social identities.

Most importantly, they should be able to build an ongoing relationship with the human who created them.

**The final experience should make users feel that they are not simply creating an avatar. They are bringing a new digital identity into a living universe.**

**Discover a Being. Meet its personality. Explore what it knows. Start a conversation. Create your own. Help it evolve.**

# IMPLEMENTATION PRIORITY

**Extend the existing MEYA application. Focus first on Discover, Being Profiles, Topic Posts and the Creator ↔ Being feedback loop.**

Do not rebuild the product, do not redesign working systems unnecessarily, and do not sacrifice existing functionality to implement the new UX.

Deliver an integrated, functioning incremental update.