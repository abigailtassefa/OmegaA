; The plugin loader adds this directory to Python's module search path.
(= (loadOmegaPlugin)
   (progn
     (add-skill render-diagram
       "Render an exact diagram from Graphviz DOT source, preserving the supplied labels and edges. Use for flowcharts, dependency graphs and architecture diagrams instead of generative image tools. Pass complete DOT source, not a natural-language description or Markdown fences. Returns a local PNG path and DOT source path; it does not send a photo."
       (dot_source))
     ()))

(= (render-diagram $source)
   (py-call (render_diagram.render_diagram $source (memoryDirectory))))
