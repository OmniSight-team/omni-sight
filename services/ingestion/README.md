# services/ingestion

Video in. Reads live camera streams and uploaded files, keeps only the frames where something
is actually moving, and passes them on to be processed.

Everything that reaches the rest of the system comes through here.
