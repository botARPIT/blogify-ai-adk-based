# Manual QA Checklist

## Auth

- [ ] Visit `/login`
- [ ] Sign in with the local seeded user or a valid local account
- [ ] Refresh a protected route and confirm session persistence
- [ ] Log out and confirm redirect back to login
- [ ] Attempt direct access to a protected route while logged out and confirm redirect

## Core workflow

- [ ] Create a blog session from the dashboard
- [ ] Confirm success toast appears
- [ ] Confirm progress page loads
- [ ] Confirm session transitions to outline review
- [ ] Revise the outline and save changes
- [ ] Approve the outline
- [ ] Confirm session resumes processing
- [ ] Confirm final review page appears
- [ ] Approve the final draft
- [ ] Confirm output page renders completed content

## Notifications

- [ ] Outline review notification appears
- [ ] Final review notification appears
- [ ] Completion notification appears
- [ ] Clicking a notification navigates to the correct route
- [ ] Mark-read behavior updates the unread count
- [ ] Toasts do not repeat endlessly during polling

## Output

- [ ] Markdown renders correctly, including inline bold and links
- [ ] Copy markdown button works
- [ ] Copy success toast appears
- [ ] Output page refresh preserves the correct content state

## Error handling

- [ ] Invalid login shows a clean user-safe message
- [ ] Missing session shows a clean user-safe message
- [ ] Any backend failure shows only message and code-derived UX, not traceback text

## Responsive checks

- [ ] Dashboard at 1440px
- [ ] Dashboard at 1024px
- [ ] Dashboard at 768px
- [ ] Dashboard at 390px
- [ ] Notification panel at narrow width
- [ ] Login page at short viewport height
- [ ] Output page on mobile
- [ ] Review pages on tablet width

## Detail and budget pages

- [ ] Session detail loads
- [ ] Latest version block is readable
- [ ] Human review events are readable
- [ ] Agent runs are readable
- [ ] Budget page loads
- [ ] Budget stats remain readable on mobile
