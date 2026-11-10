#include <stdint.h>

#if PATTERN == 10
#pragma HLS interface port = in mode = bus
#else
#pragma HLS interface port = in mode = m_axi offset = direct
#endif
#pragma HLS interface port = out mode = m_axi offset = direct

void memory_pattern(volatile uint32_t *in, volatile uint32_t *out)
{
#if PATTERN == 1
    uint32_t state = in[0];
    for (unsigned i = 0; i < 1000; ++i)
        state = (state ^ (i + 1)) * 33u;
    out[0] = state ^ in[1];
#elif PATTERN == 2
    out[0] = in[0];
#elif PATTERN == 3
    in[1] = in[0] ^ 0x12345678u;
    out[0] = in[1];
#elif PATTERN == 4 || PATTERN == 10
    for (unsigned i = 0; i < WORDS; ++i)
        out[i] = in[i] ^ 0x55aa55aau;
#elif PATTERN == 5
    for (unsigned i = 0; i < WORDS; ++i)
        out[i] = in[(73u * i) & (WORDS - 1)] + i;
#elif PATTERN == 6
    volatile unsigned char *bytes = (volatile unsigned char *)in;
    bytes[0] = 0x11;
    bytes[1] = 0x22;
    bytes[2] = 0x33;
    bytes[3] = 0x44;
    out[0] = in[0];
#elif PATTERN == 7
    uint32_t sum = 0;
    for (unsigned i = 0; i < 1024; ++i)
        sum += in[(i & 1u) * STRIDE];
    out[0] = sum;
#elif PATTERN == 8 || PATTERN == 9
    uint32_t sum = 0;
    for (unsigned i = 0; i < WORDS; i += STRIDE)
        sum += in[i];
    out[0] = sum;
#else
#error Unknown PATTERN
#endif
}
