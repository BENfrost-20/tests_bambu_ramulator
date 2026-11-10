#include <stdint.h>
#include <stdio.h>

void memory_pattern(volatile uint32_t *in, volatile uint32_t *out);

static uint32_t input[WORDS];
static uint32_t output[OUT_WORDS];

static uint32_t initial(unsigned i)
{
    return 17u + 3u * i;
}

static uint32_t expected(unsigned i)
{
#if PATTERN == 1
    uint32_t state = initial(0);
    for (unsigned k = 1; k <= 1000; ++k)
        state = (state ^ k) * 33u;
    return state ^ initial(1);
#elif PATTERN == 2
    return initial(0);
#elif PATTERN == 3
    return initial(0) ^ 0x12345678u;
#elif PATTERN == 4 || PATTERN == 10
    return initial(i) ^ 0x55aa55aau;
#elif PATTERN == 5
    return initial((73u * i) % WORDS) + i;
#elif PATTERN == 6
    return 0x44332211u;
#elif PATTERN == 7
    return 512u * (initial(0) + initial(STRIDE));
#elif PATTERN == 8 || PATTERN == 9
    uint32_t count = WORDS / STRIDE;
    return count * initial(0) + 3u * STRIDE * (count * (count - 1u) / 2u);
#endif
}

int main(void)
{
    for (unsigned i = 0; i < WORDS; ++i)
        input[i] = initial(i);
    memory_pattern(input, output);
    for (unsigned i = 0; i < OUT_WORDS; ++i) {
        uint32_t want = expected(i);
        if (output[i] != want) {
            fprintf(stderr, "CHECK FAIL: output[%u]=%u expected=%u\n", i, output[i], want);
            return 1;
        }
    }
    for (unsigned i = 0; i < WORDS; ++i) {
        uint32_t want = initial(i);
#if PATTERN == 3
        if (i == 1)
            want = expected(0);
#elif PATTERN == 6
        if (i == 0)
            want = expected(0);
#endif
        if (input[i] != want) {
            fprintf(stderr, "CHECK FAIL: input[%u]=%u expected=%u\n", i, input[i], want);
            return 1;
        }
    }
    puts("MICRO CHECK PASS");
    return 0;
}
