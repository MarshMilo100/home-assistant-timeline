done:
- auto fade to warm
- set min and max color temperature based on what each light supports
- change commit author
- continue to update the color temperature slider when moving the node on the graph
- update the color temperature gradient on the graph view area under the graph to match the color temperature of the node. Update the opacity of the node and gradient under the graph to represent the brightness of the light.
- hover help text for fade to warm checkbox to specify to the user that the option automatically ties color temperature to brightness.
- add snapping points for sunrise and sunset
- add support for different days of the week.
- allow interrupting the scheduler by manually setting the light state until the next scheduled event
  - when easing is selected into the next node, that easing selection should still be respected when transitioning from a manual state to a scheduled one.
- split type of easing to easing in and easing out setting to allow more customizability.
- add toggle at the top to allow accordion functionality or to keep all timelines open
- allow overlaying individual days of the week on top of the same timeline.

todo:
- add support to tie light brightness to cloud coverage to turn lights on if it gets cloudy.
  - Allow setting a min and max brightness within which the lights will be set.
- add templates and examples for timelines, and add exporting and importing specific timelines, nodes, and whole schedules.
- add options for easing time. If easing time is less than time to next node, hold the current state until the easing is set to begin.
- add readme that documents all major features, including screenshots.
- 24hr or 12hr time
