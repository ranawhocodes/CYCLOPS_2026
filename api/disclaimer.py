"""
The scope statement.

Lives in its own module so both the app description and the /v1/disclaimer
endpoint use the same text, and so neither has to import the other. One string,
one source, shown verbatim on the console.
"""

DISCLAIMER = (
    "CYCLOPS is a decision-support and nowcasting aid intended to assist trained "
    "forecasters. It is not a substitute for the operational warnings issued by "
    "the India Meteorological Department, which remains the sole authority for "
    "tropical cyclone warnings in the North Indian Ocean. Prediction is limited "
    "to a 6-24 hour horizon. Intensity estimates are trained against best-track "
    "records that are themselves partly derived from subjective Dvorak analysis, "
    "and the system's accuracy is therefore bounded by the consistency of that "
    "record."
)
