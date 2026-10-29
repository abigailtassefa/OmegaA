!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ../src/logger.py)
!(import! &self ../src/plugin.py)
!(import! &self ../src/config.py)
!(import! &self ./src/utils)
!(import! &self ./src/log)
!(import! &self ./src/skills)
!(import! &self ./src/plugin)

(= (memoryDirectory) "/tmp/omega-diagram-integration")

!(test (loadPlugin (metta "render_diagram" "./plugins/render_diagram")) ())

!(test
   (collapse (match &self
     (dynamic-skill render-diagram (render-diagram $description (dot_source)))
     registered))
   (registered))

!(test
   (contains-text
     (render-diagram "digraph { request -> model; model -> tool; tool -> model; }")
     "DIAGRAM_RENDERED:")
   True)

!(test
   (contains-text (render-diagram "digraph { a -> }") "DIAGRAM_FAILED:")
   True)

!(test
   (contains-text (render-diagram "") "DIAGRAM_FAILED:")
   True)
