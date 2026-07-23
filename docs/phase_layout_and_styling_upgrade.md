# Phase: Layout and Styling Upgrades

## Goal

Make Friend Hub feel like a polished, attractive mobile-first social app rather than a functional prototype.

The design direction should be:

Private group chat meets social dashboard.

The app should feel warm, playful, clean, and useful. It should not feel corporate, generic, or overly childish.

## Design Direction

Use a consistent visual language across all main pages:

- Home
- Chat
- Items
- More
- Events
- Polls
- Reminders
- Calendar
- Photos
- Settings

Target feeling:

- Cosy
- Social
- Mobile-native
- Slightly playful
- Clean and readable
- Premium enough to feel intentional

## Core Style System

Introduce shared design tokens for:

- Colours
- Backgrounds
- Text colours
- Border colours
- Border radius
- Shadows
- Spacing
- Badge styles
- Card styles
- Button styles
- Chat bubble styles

Suggested base style:

- Background: soft off-white or pale blue-grey
- Main surface: white or very light blue-grey
- Primary: warm indigo or violet
- Accent: orange or coral
- Success: green
- Warning: amber
- Text: dark navy
- Muted text: slate grey
- Border radius: 16px to 24px
- Shadows: soft and subtle
- Borders: low-contrast grey-blue

Avoid harsh pure black and pure white where possible.

## Theme System

Add a simple theme setting that lets users choose from a small set of colour palettes.

This should live in Settings.

Each theme should define:

- App background
- Card background
- Primary colour
- Secondary colour
- Accent colour
- Text colour
- Muted text colour
- Border colour
- Bot message colour
- Own chat bubble colour
- Navigation colour
- Badge colours

Start with a small set of themes rather than making every colour individually customisable.

Suggested themes:

### Classic Hub

The default Friend Hub look.

- Soft grey-blue background
- White cards
- Indigo primary
- Orange accent
- Dark navy navigation

### Night Out

A darker, pub/night-out inspired theme.

- Deep navy background
- Dark cards
- Purple primary
- Warm amber accent
- Light text

### Soft Pastel

A softer casual theme.

- Cream or pale pink background
- White cards
- Lavender primary
- Coral accent
- Slate text

### Forest

A calmer earthy theme.

- Pale sage background
- Off-white cards
- Forest green primary
- Amber accent
- Dark olive text

### Retro

A slightly playful theme.

- Warm cream background
- Muted blue primary
- Burnt orange accent
- Dark brown/navy text

## Theme Implementation Notes

Create a central theme configuration file.

Example shape:

    {
      id: "classic-hub",
      name: "Classic Hub",
      description: "Clean, social, and balanced.",
      colours: {
        background: "...",
        surface: "...",
        surfaceAlt: "...",
        primary: "...",
        primaryText: "...",
        accent: "...",
        text: "...",
        mutedText: "...",
        border: "...",
        navBackground: "...",
        ownMessage: "...",
        botMessage: "..."
      }
    }

Expose the selected theme through CSS variables on the app root.

Example variables:

    --color-background
    --color-surface
    --color-surface-alt
    --color-primary
    --color-primary-text
    --color-accent
    --color-text
    --color-muted-text
    --color-border
    --color-nav-background
    --color-own-message
    --color-bot-message

Persist the selected theme in the database if user-specific settings exist.

Otherwise, start with local storage.

## Global Layout Upgrades

Apply a subtle app-wide background.

Preferred option:

- Soft vertical gradient
- Very subtle colour shift from top to bottom
- No loud patterns initially

Use consistent page padding:

- Mobile: 16px
- Larger screens: centred app shell with max width

Cards should share a consistent style:

- Rounded corners
- Soft shadow
- Light border
- Comfortable padding
- Clear title hierarchy

Buttons should share consistent variants:

- Primary
- Secondary
- Ghost
- Danger
- Pill
- Icon button

## Home Page Upgrades

The home page is already the strongest part of the app.

Keep the image header direction, but improve polish.

### Header

Upgrade the header card:

- Slightly taller
- Stronger bottom overlay
- Larger Friend Hub title
- Show message count and online status clearly
- Display pinned items as small glassy pills
- Allow header image to be customised later from Photos
- Clicking the header can open a modal with options to reposition or change the image

Suggested header content:

    Friend Hub
    13 messages today · 3 online

    Pinned: pub?
    Live poll
    Next event

### Latest Chat

Refine the latest chat card:

- Better spacing between messages
- More consistent avatar sizes
- Softer card styling
- Slightly clearer timestamp styling
- Keep message preview short and tidy

### Recent Activity

Make Recent Activity feel like a social feed.

Upgrade cards with:

- Better badges
- Clearer title and metadata
- Stronger visual hierarchy
- Avatar/reaction indicators
- Cleaner carousel controls
- Better contrast over gradients

Activity cards should support:

- Hot poll
- New event
- Reminder due
- Photo uploaded
- Comment added
- Item pinned
- Hub Bot suggestion

## Chat Page Upgrades

Keep the current chat direction, but refine it.

### Chat Background

Use a soft background rather than flat white.

Options:

- Soft gradient
- Very faint pattern
- Slight blue-grey tint

Avoid anything that reduces message readability.

### Message Bubbles

Refine bubble styles:

Own messages:

- Warm indigo or violet
- White text
- Soft shadow
- Rounded corners

Other messages:

- White or very light surface
- Dark text
- Soft border
- Subtle shadow

Bot messages:

- Pale blue or pale indigo
- Bot badge
- Slightly different border
- Optional sparkle or bot icon

### Hub Bot Identity

Make Hub Bot visually distinct.

Use:

- Special avatar
- BOT badge
- Pale bot bubble
- Online status
- Optional quick action buttons

Example bot message:

    Hub Bot ✨
    I can help plan this. Want me to turn it into a poll?

    Create poll
    Add reminder

### Message Input

Improve the input bar:

- Sticky at bottom
- Slight glass/blur background
- Larger send button
- Primary colour plus button
- Clear disabled state
- Safe-area padding for mobile
- Better spacing between input, plus, and send

## Items Page Upgrades

This page has the biggest opportunity.

Move from plain stacked cards to a richer hub dashboard.

### Category Cards

Each item type should have:

- Icon
- Title
- Description
- Count or status
- Latest item preview
- Accent colour or gradient
- Clear tap target

Suggested categories:

- Ideas
- Polls
- Events
- Reminders
- Calendar
- Photos

Consider a two-column grid on mobile:

    Ideas       Polls
    Events      Reminders
    Calendar    Photos

Or use full-width cards if previews are more important.

### Recent Items

Add a recent items section below the category cards.

Example:

    Recently updated

    #P-7 Council motion
    Poll · 4 votes · updated 2h ago

    #E-4 BBQ next Saturday
    Event · 6 attendees · updated yesterday

    #I-12 Amsterdam idea
    Idea · 3 comments · updated Monday

## More Menu Upgrades

Replace the current floating dark menu with a more mobile-native pattern.

Preferred option:

### Bottom Sheet

Tapping More opens a bottom sheet.

The sheet should include:

- Photos
- Stats
- Members
- Server
- AI
- Settings

Each option should have:

- Icon
- Title
- Short description
- Optional count/status

Example:

    Photos
    Group memories and uploads

    Stats
    Activity, voting, and chat trends

    Members
    People, roles, and permissions

    AI
    Hub Bot settings and memory

    Settings
    Theme, notifications, and preferences

Alternative:

Use a full More page with cards if the bottom sheet becomes too crowded.

## Event and Poll Card Upgrades

Current event cards are functional but too dense.

Improve visual hierarchy.

Suggested structure:

    #E-7  EVENT
    Past event

    Council motion scheduled

    Monday 11 May · 10:26 PM
    Owner: lololhahahaa

    Open

    Votes
    Yes       0
    Maybe     0
    No        0

    React · 0 reactions · 0 comments

### Event Card Rules

- Put metadata near the top
- Make title/action clear
- Keep voting/results grouped
- Move social actions to the footer
- Avoid too many borders inside the card
- Use spacing and typography rather than boxes everywhere

## Icons

Use consistent line icons across the app.

Suggested icons:

- Ideas: lightbulb
- Polls: bar chart or vote
- Events: calendar
- Reminders: bell
- Calendar: calendar-days
- Photos: image
- Stats: activity or chart
- Members: users
- AI: bot or sparkles
- Settings: cog
- Pinned: pin
- Chat: message-circle
- More: menu
- Comments: message-square
- Reactions: smile or heart

Use emoji sparingly for fun badges only.

## Empty States

Add polished empty states.

Each empty state should have:

- Icon
- Short title
- Friendly explanation
- One clear action where useful

Examples:

    No pinned items yet
    Pin a poll, idea, event, or reminder to keep it here.

    No live poll
    Start one from the Agenda button.

    No recent activity
    When people vote, comment, react, or add ideas, they’ll appear here.

    No photos yet
    Upload the first group memory.

## Loading States

Add better loading states:

- Skeleton cards
- Skeleton chat messages
- Spinner only where unavoidable
- Avoid layout jumping

## Responsive Behaviour

Design mobile-first.

For larger screens:

- Centre the app content
- Use a comfortable max width
- Avoid stretching cards too wide
- Consider a two-column layout for dashboard pages
- Chat should remain readable rather than full-width

## Accessibility

Ensure:

- Strong enough colour contrast
- Tap targets are large enough
- Text is readable on gradients
- Buttons have clear labels
- Theme choices do not break contrast
- Focus states exist for keyboard navigation
- Reduced motion is respected where animations are added

## Implementation Plan

### Step 1: Add Design Tokens

Create shared CSS variables for colours, radius, spacing, shadows, and surfaces.

Apply them globally before redesigning individual pages.

### Step 2: Add Theme System

Create theme definitions.

Add a Settings UI for selecting a theme.

Persist the selected theme using local storage first, or database-backed user settings if already available.

### Step 3: Update Shared Components

Upgrade:

- Page shell
- Cards
- Buttons
- Badges
- Bottom navigation
- Avatars
- Modals
- Bottom sheets
- Empty states
- Loading skeletons

### Step 4: Upgrade Home

Improve:

- Header image card
- Pinned pills
- Latest chat
- Recent activity cards

### Step 5: Upgrade Chat

Improve:

- Background
- Message bubbles
- Bot bubble
- Input bar
- Quick actions

### Step 6: Upgrade Items

Replace simple stacked cards with richer category cards and recent items.

### Step 7: Upgrade More

Replace floating menu with bottom sheet or full-page card menu.

### Step 8: Upgrade Event and Poll Cards

Improve hierarchy, spacing, badges, voting layout, and footer actions.

### Step 9: Polish

Add:

- Empty states
- Loading skeletons
- Better mobile spacing
- Safe-area padding
- Small transitions
- Final contrast checks

## Acceptance Criteria

The phase is complete when:

- The app has a consistent visual language across all main pages
- A user can choose from multiple themes
- Theme choice persists between sessions
- Home feels polished and social
- Chat still feels familiar but cleaner
- Hub Bot has a distinct visual identity
- Items page feels like a real dashboard
- More menu feels mobile-native
- Event and poll cards are easier to scan
- Empty states look intentional
- Mobile layout remains the priority
- Existing functionality is not broken

## Notes

Do not redesign everything into a corporate SaaS dashboard.

Friend Hub should feel like a private social app for a real friend group.

Prioritise warmth, clarity, and fun.