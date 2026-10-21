# Dial + Radial Menu Interaction Research

Goal: design a dial-driven radial menu for a PC. Our dial's inputs are:
- rotate CW/CCW (discrete steps, no haptics)
- single / double / triple press, decoded by firmware (a single press arrives ~300-500 ms late)
- press-and-hold (one event, no release event)

Note: research collected Oct 2026. Where a fact comes from memory or a secondary source and not a primary doc, it is marked *(secondary)*.

---

## 1. Microsoft Surface Dial (RadialController)

Source: https://learn.microsoft.com/en-us/windows/apps/design/input/windows-wheel-interactions

**Gesture model**
- Three gestures: rotate, click, press-and-hold.
- Press-and-hold has exactly one job: open the system menu. Apps get nothing else from it.
- While the menu is open, the menu consumes rotate and click. When it's closed, the app gets them.
- A click becomes a hold once a time threshold passes. The threshold is internal and not documented. Apps can suppress the menu and handle `ButtonHolding` themselves: https://learn.microsoft.com/en-us/uwp/api/windows.ui.input.radialcontrollerconfiguration.ismenusuppressed

**Tool model (the key idea)**
- The menu does not run commands. It picks a tool, such as Volume, Scroll, Zoom, Undo, Brush size, or Ruler.
- After the menu closes, rotate and click act on the chosen tool until the user picks another one.
- Users spend most of their time in a tool, not in the menu.
- Microsoft recommends one custom tool per app context. The app can then switch the active tool to match what the user is doing, so the user doesn't have to open the menu at all.

**Menu content rules**
- The menu has room for 7 items. With 8 or more, an overflow flyout appears that you reach by turning, and Microsoft calls that hard to use.
- Items have no disabled state. Add and remove them as the context changes, and remove any that don't apply.
- Keep the order of items consistent so people can learn where things are.
- Always keep Volume and Next/Previous track.
- A tool's name should state its main action, with the opposite action implied ("Scroll" covers both directions, "Undo" implies Redo).
- Icons: 64x64 PNG (44x44 minimum) with a transparent background, plus a black outline so they work in high-contrast mode.

**Rotation and haptics**
- Default resolution: an event fires every 10° of rotation, and each event gives a haptic tick.
- `RotationResolutionInDegrees` is adjustable.
- Turn haptics off below 5° per event, or for continuous or high-sensitivity tools, because constant buzzing feels bad.
- Direction mapping: CW = right / down / "in" (zoom in). CCW = left / up / out. Mirror this for right-to-left locales.

**Click rules**
- Click only for actions that can be undone, and binary toggles are best (mute, show/hide).
- Never use click to turn a modal tool on or off.

**Menu placement**
- Off-screen use: the menu appears at screen center, and the user can drag it.
- On-screen use (Dial placed on a Surface Studio): the menu wraps around the device. The UI moves itself to avoid the hand, which sits on the opposite side from the writing hand.
- No auto-dismiss timeout is documented. The menu closes when you click to select. *(secondary: re-holding also closes it)*

---

## 2. Logitech

### MX Creative Console (Dialpad) + Actions Ring
Sources: https://support.logi.com/hc/en-ca/articles/27046845711511 , https://support.logi.com/hc/en-us/articles/17859989812503 , https://www.logitech.com/en-us/software/logi-options-plus/actions-ring.html
- The Dialpad has one large dial, a scroll wheel, and 4 buttons. Its behavior changes with the active app.
- The Actions Ring is an on-screen overlay of **8 bubbles** that appears at the cursor. A dedicated button on the Dialpad opens it. On other MX devices, any button can be assigned to "Show Actions Ring".
- Bubbles can be **actions** (click to run) or **adjustments**. For an adjustment, you hover over it and turn the dial.
- Once you pick an adjustment, the dial keeps controlling it after the ring closes. This is the same "pick a tool, then the dial drives it" model as the Surface Dial.
- Ring contents change per app (Photoshop, Premiere, Figma, Office, and others).
- Review context: https://www.digitalcameraworld.com/photography/video-editing/logitech-mx-creative-console-review , https://petapixel.com/2024/09/24/logitech-mx-creative-console-review-taking-the-tedium-out-of-editing

### MX Master thumbwheel / SmartShift / app profiles
Sources: https://support.logi.com/hc/en-us/articles/360023459853 , https://hub.sync.logitech.com/mx-master-4/post/getting-started---mx-master-4-LSEt5tZXsbeMP3c
- Per-app profiles change what the thumbwheel does: horizontal scroll in Excel, zoom in PowerPoint, tab switching in browsers, brush size in Photoshop.
- SmartShift switches the main wheel from ratchet (one notch per step) to free-spin once the user scrolls faster than a threshold. The threshold is user-adjustable. This is hardware **speed-dependent acceleration**: slow turns are precise, fast turns cover distance.
- The Gestures button works like this: tap it for one action, or hold it and move in one of 4 directions for others. That's a 4-way directional menu with no visuals.

---

## 3. Loupedeck / Razer Stream Controller
Sources: https://support.loupedeck.com/control-elements-live.html , https://mysupport.razer.com/app/answers/detail/a_id/6153 , https://gamesradar.com/loupedeck-live-review , https://www.windowscentral.com/accessories/razer-stream-controller-review
- Dials are stepped (detented). Turning changes a value, and pressing either resets it to default or toggles something.
- Pressing the dial to **reset** the value is the common pattern across Loupedeck and Razer.
- A dial does different things on different pages or workspaces.
- On the Razer, a small screen next to each dial shows its **current function and value**. Showing what the dial will act on right next to it is the strongest feedback pattern in this category.
- Reviews say small adjustments feel great, but large changes take several turns. This argues for acceleration on value tools.

## 4. Griffin PowerMate
Sources: https://en.wikipedia.org/wiki/Griffin_PowerMate , https://tidbits.com/2002/10/28/unleashing-the-power-of-the-powermate/ , https://www.macworld.com/article/207617/griffinpowermate3software.html
- Inputs: rotate left/right, press, long press (hold time adjustable from 0.5 to 4 s), and press-while-rotating as a separate modifier layer.
- Profiles switch with the focused app, falling back to a default profile.
- The LED base gives ambient visual feedback, such as showing the volume level.
- Early reviews noted lag at the start of a turn. The first step has to land immediately.

## 5. Apple Digital Crown
Sources: https://developer.apple.com/design/human-interface-guidelines/digital-crown , https://developer.apple.com/documentation/swiftui (see `digitalCrownRotation`; API details from memory)
- By default, the Crown gives linear haptic detents: one tap per fixed distance turned. Lists give one detent per row. If the default detents don't match your animation, turn them off. Feedback that disagrees with the visuals is worse than none.
- Always give visual feedback, and match update speed to turning speed. The Crown is supposed to feel precise and directly connected.
- SwiftUI parameters (*secondary*): `from/through` (bounds), `by` (step size, i.e. detents), `sensitivity` (low/medium/high), `isContinuous` (wrap around vs. stop at the ends), `isHapticFeedbackEnabled`, and an `onIdle` callback when the user stops turning.
- At list ends, lists **rubber-band**: they move a little past the end, slow down, and spring back. That signals "end" without a hard wall. Scrolling has momentum and stops at the nearest row. *(secondary, standard watchOS behavior)*

## 6. iPod click wheel
Sources: https://en.wikipedia.org/wiki/IPod_click_wheel , https://www.vice.com/en/article/ipod-click-wheel-best-interface-ever , https://forums.macrumors.com/threads/new-ipod-scroll-wheel.8073
- Scroll speed follows finger speed. Fast circles fly through hundreds of items, and slowing down slows scrolling immediately, with no coasting to wait out. Users found this more controllable than flick-and-coast scrolling.
- A **click sound plays on every step** (from a piezo speaker on early models, *secondary*) in place of haptics. This is the closest precedent for a dial with no haptics.
- The same ring changes job with context: it moves through lists in menus and controls volume during playback.

## 7. Teenage Engineering (OP-1)
Source: https://teenage.engineering/guides/op-1/original/layout
- The 4 encoders are color-coded, and the on-screen element each one controls uses the same color. That gives an instant link between knob and target without any labels.
- Shift + turn gives a second layer. Encoder pushes are detected separately as short or long presses.

---

## 8. Pie / marking menu research

**Callahan, Hopkins, Weiser, Shneiderman (CHI '88): "An Empirical Comparison of Pie vs. Linear Menus"**
https://doi.org/10.1145/57167.57182 , https://sites.umiacs.umd.edu/node/16962
- Pie menus were about 15% faster with fewer errors than linear menus, and users rated them about the same.
- Why: every item is the same short distance from the center and has a large, wedge-shaped target (Fitts' law).
- Hopkins also promotes "mouse-ahead": experts flick in the remembered direction before the menu even draws. Retrospective: https://www.osnews.com/story/30371/pie-menus-a-30-year-retrospective/

**Kurtenbach & Buxton (InterCHI '93): "The Limits of Expert Performance Using Hierarchic Marking Menus"**
https://www.billbuxton.com/MMExpert.html , https://research.autodesk.com/app/uploads/2023/03/the-limits-of-expert.pdf_recyw5wL6ekPqcE4Q.pdf
- Marking menus are designed so beginners and experts use the same gesture. Beginners press, wait, and see the menu. Experts just make the mark, and the menu never appears. Practice turns into skill without relearning.
- Breadth and depth limits for under 10% errors: 8 items per level allows at most 2 levels. 4 items per level allows up to 4 levels. Menus with 2, 4, 6, 8, or 12 items work. 8 positions on the compass directions (and 4) are the easiest.
- Follow-up on simple marking menus: https://www.dgp.toronto.edu/~ravin/papers/uist2004_simplemm.pdf

**Fitts' law, and why it mostly doesn't apply to us**
- Fitts' law explains the pie menu advantage for a **pointer**. A dial has no pointer. Selection cost is the **number of steps** from where the highlight starts to the target, plus the time to check where you are.
- The dial version of the pie menu advantage: keep the menu small and the order fixed, and start the highlight in a predictable place. Then every item is a known, small number of clicks away. Wrap-around halves the worst case (N/2 steps).

**Game weapon wheels**
Sources: https://300mind.studio/blog/radial-menus-in-game-design/ , https://doomwiki.org/wiki/BFG_weapon_wheel_slowdown , https://allthings.how/gta-6-how-the-weapon-wheel-and-inventory-work/
- Typical flow: hold a button to open the wheel, aim with the stick in a direction, release to confirm. The selection is **directional and absolute**, so you don't step through items one at a time.
- Time slows down or pauses while the wheel is open, which takes away time pressure. Players are split: many call it tempo-breaking and want a quick-switch key (tap = last weapon).
- 4-8 segments works best. Use sub-wheels for overflow. A fixed layout builds muscle memory.
- Show the current item and the highlighted item. Highlight by scaling or brightening. Releasing on the center or in the dead zone cancels.
- Our dial has **no release event and no direction input**, so the release-to-confirm and directional-aim parts don't carry over. What does carry over: a small fixed ring, a "last item" quick-switch, a cancel path, and freezing what's behind the menu.

---

## 9. Animation, feedback, latency

**Apple "Designing Fluid Interfaces" (WWDC18)**
https://developer.apple.com/videos/play/wwdc2018/803/
- Describe springs by **damping** and **response**, not by duration. 100% damping means no overshoot. Use around 80% only when the motion carries momentum.
- Springs can be **retargeted mid-flight**, which suits rapid dial steps: each step just moves the target.
- Rubber-band at boundaries instead of stopping dead.
- Highlight right away on input. Waiting for a double-tap delays single taps by about 0.5 s and users feel it, so avoid that when you can. This is exactly our firmware's single-press problem.
- Detect intent as early as possible. 60 fps (or higher) is needed so fast motion doesn't strobe.

**Response-time limits (Nielsen)**
https://www.nngroup.com/articles/response-times-3-important-limits/
- Under 0.1 s feels instant, like direct manipulation. Up to 1 s keeps the user's flow. Beyond 10 s they lose attention.
- Each dial step must show visible movement well under 100 ms. Aim for the next frame, about 16 ms after the event.

**Feedback without haptics**
- Use an audio tick per step (iPod precedent). Keep it short (under 30 ms), quiet, and slightly pitched. A different sound at the boundary or on wrap tells you where you are without looking. Make it optional.
- Visual snap: the highlight jumps to the next item and settles with a critically damped spring of about 120-200 ms. Use a little overshoot only if the dial gives no other cue. The user should never wait for the animation before reading the new selection.
- Coalesce quick steps: when steps arrive faster than the animation, retarget the spring instead of queuing animations.
- Acceleration (encoder velocity to a step multiplier) helps value tools. It hurts discrete menus, because users count clicks. Patterns: https://docs.rs/rotary-encoder-embedded/0.5.0/rotary_encoder_embedded/struct.RotaryEncoder.html , https://docs.rs/sb-rotary-encoder

---

## Principles we should adopt

Based on our inputs: discrete rotate steps, no haptics, a single press that arrives ~300-500 ms late, double/triple press, and a hold event with no release.

1. **Use the tool model, not a command palette.** Hold opens the menu. Rotating picks a tool, and the press confirms it. After that, rotate drives the active tool with no menu on screen. The dial lives in "tool mode" 95% of the time (Surface Dial, Actions Ring).

2. **Make the menu a toggle, not hold-to-show.** We get no release event, so release-to-confirm (as in weapon wheels) is impossible. Hold opens the menu. Holding again, or double-pressing, closes it without changing anything.

3. **Keep at most 8 items, ideally 4-6, in one level.** Microsoft fits 7 before overflow. Logitech uses 8. Kurtenbach & Buxton: 8 items works for at most 2 levels. With no pointer, every extra item costs another click, so avoid submenus if you can. If you need them, allow only one level of 4 or fewer.

4. **Keep the order fixed and open with the highlight on the active tool.** Never reorder by frequency. Users should learn "Zoom is two clicks clockwise from Volume." Hide items that don't apply instead of greying them out (Surface rule), but keep the relative order of the items that remain.

5. **Wrap around in the menu, and use soft ends for values.** With 8 or fewer items, wrap-around keeps any item within N/2 steps. For value tools, stop at min/max with a short rubber-band nudge plus a distinct "end" tick (Digital Crown).

6. **One step = one item in the menu, with no acceleration.** Clicks need to be countable. In value tools, add speed-based acceleration (SmartShift, iPod): slow turns move exactly 1 unit per step, and fast bursts multiply. Reset the multiplier after about 150 ms of no input.

7. **Show the highlight immediately on every rotate step.** Move it within the next frame (under 16 ms render, under 100 ms total). Use a critically damped spring, about 150 ms response. Retarget it mid-flight instead of queuing, so fast spins never lag behind the dial.

8. **Replace haptics with audio and visual detents.** Play a short tick per step (iPod) and a different sound at the ends or on wrap. Animate a clear snap on each step: the highlighted wedge grows and brightens while the previous one fades. The tick and the snap must happen together. A tick without visual movement, or the other way round, feels broken (Apple's "disable detents if they don't match the animation").

9. **Hide the single-press delay.** We can't detect the press until the firmware decides it wasn't a double press. Two ways to cope:
   - Make "confirm" feel deliberate: when the event arrives, play a fast (about 100 ms) confirm animation and close the menu straight away.
   - Better: **auto-apply on rotate**. In the menu, the highlighted tool already drives a live preview, or becomes active as soon as the menu closes. The press then only closes the menu, so its delay costs nothing.

   Never make the user wait on a single press for continuous, back-and-forth work.

10. **Use single press for reversible or binary actions only (Surface rule).** In tool mode, a single press means toggle, reset to default (Loupedeck and Razer), or play/pause. Never use it for something destructive. Double press = secondary, still reversible. Triple press = rare (for example "back to default tool"), since triple presses are slow and error-prone.

11. **Give the last tool a quick switch.** Weapon-wheel players hate opening the wheel just to swap back. Add a gesture that toggles between the current and previous tool with no menu. Double press in tool mode is a good fit.

12. **Auto-dismiss on idle, safely.** Close the menu after about 4-6 s with no input, and keep the active tool the same, not the highlighted one, unless auto-apply (rule 9) is on. Always provide an explicit cancel.

13. **Always show what the dial is bound to (Razer, OP-1).** In tool mode, show a small, unobtrusive "HUD pill" on the first rotate: tool icon, value, and a bar. Let it fade out after about 1.5 s of idle. It answers "what will this turn do?" without opening the menu.

14. **Keep the menu at a fixed, predictable spot, with no pointer aiming.** Center it on the screen (Surface off-screen default) or on the focused window. Draw it large, with icon and label in each wedge and the highlighted tool's name in the center hub (Surface pattern). Don't freeze or dim the app more than a light scrim, because the user may be watching a live preview.

15. **Follow the platform's direction conventions.** CW = increase / right / down / zoom in. CCW = the opposite. Mirror for right-to-left locales (Surface table). Keep the menu's highlight moving clockwise for CW turns.

16. **Let tools and menu contents change with the foreground app.** Use per-app profiles that fall back to a default (PowerMate, Logitech, Surface). Always keep Volume and media controls available (Surface rule).
