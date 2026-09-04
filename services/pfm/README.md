# services/pfm

The Predictive Forecasting Module. Looks at recent activity and predicts what is likely to
happen next, with a time estimate and a confidence.

It also holds the verification cascade, which filters predictions from cheap quick checks up
to careful review, so an operator sees candidates instead of noise.
