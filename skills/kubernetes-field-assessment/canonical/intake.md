# Analysis Start Card

The analysis start card is choice-first. The user can press Enter to accept the
recommended default, choose a numbered option, or provide direct input when the
choices do not fit.

Do not ask "what did the customer select" in user-facing wording. Ask about the
application and current execution shape.

## Required Question Semantics

Ask only for minimal context needed to guide repository assessment:

- application shape, such as web/API server, batch, worker, static frontend, or
  unknown;
- current execution shape, such as VM, WAS/Tomcat/WebLogic, Docker/Compose,
  existing Kubernetes, or unknown;
- first analysis purpose, such as migration field diagnosis, manifest input
  preparation, risk/follow-up question review, or gap repair.

Direct input must be normalized into structured meaning and confirmed before it
changes the assessment scope.
