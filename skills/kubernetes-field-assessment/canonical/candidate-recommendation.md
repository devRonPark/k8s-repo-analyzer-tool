# Application Candidate Recommendation

After the analysis start card, run a cheap repository scan before asking the
model to reason about scope. This step recommends the most likely application
target for Kubernetes Migration Field Assessment without sending full repository
text to the model.

## Cheap Scan Rule

Use path, file kind, file size, manifest metadata, package metadata, and short
source context collected from high-signal files. Do not send full repository
text, file contents, binary contents, or secrets as the candidate discovery
input.

## Candidate Display

Render each detected candidate with:

- a number the user can select;
- a field-friendly display name;
- a short evidence summary;
- a short reason why this candidate is recommended or listed.

Mark the most likely candidate as recommended. Blank input means "select the
recommended candidate and advance." A number selects that candidate. If the user
does not see the right candidate, let them provide direct input and normalize it
before changing scope.

The machine-readable contract lives in
`canonical/candidate-recommendation.json`. Runtime adapters may render the
choices differently, but must preserve the cheap scan policy and selection
semantics.
