#ifndef VADD_H
#define VADD_H

// Top function under test. Signature is part of the interface contract:
// the agent must NOT change this without explicit task permission.
void vadd(const int *a, const int *b, int *c, int n);

#endif // VADD_H
