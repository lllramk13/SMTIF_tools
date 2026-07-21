LZ77_MAGIC = b'\x01\x02\x00\x00'
RLE_MAGIC = b'\x01\x01\x00\x00'
RAW_MAGIC = b'\x01\x00\x00\x00'


class LZ77Compressor:
    """Compress bytes using SMT if's 0x01/0x02 LZ77 resource format."""

    def encode_literal(
        self,
        data: bytes,
        encoding_ptr: int,
        lz_seeker: int,
    ) -> bytes:
        """Encode literal runs; each token can contain at most 0x80 bytes."""
        literal_output = bytearray()

        for position in range(encoding_ptr, lz_seeker, 0x80):
            entry_length = min(0x80, lz_seeker - position)
            literal_output.append(entry_length - 1)
            literal_output.extend(data[position:position + entry_length])

        return bytes(literal_output)

    def lz_match_getter(
        self,
        data: bytes,
        lz_seeker: int,
        file_size: int,
    ) -> tuple[int, int] | None:
        """Find a match in the preceding 0x100-byte sliding window."""
        entry_length = 3
        lookback = -1
        match = None

        # This intentionally preserves the predecessor's search strategy.
        while lookback >= -0x100 and entry_length <= 0x82:
            if lz_seeker + lookback < 0 or lz_seeker + entry_length > file_size:
                break

            current_data = data[lz_seeker:lz_seeker + entry_length]
            lookback_data = data[
                lz_seeker + lookback:lz_seeker + lookback + entry_length
            ]

            if current_data == lookback_data:
                match = (entry_length, lookback)
                entry_length += 1
            else:
                lookback -= 1

        return match

    def compress(self, input_data: bytes) -> bytes:
        """Return a complete 0x01/0x02 resource, including its 12-byte header."""
        input_data = bytes(input_data)
        file_size = len(input_data)
        encoding_ptr = 0
        lz_seeker = 1
        output = bytearray()

        while encoding_ptr < file_size:
            if lz_seeker >= file_size:
                output.extend(
                    self.encode_literal(input_data, encoding_ptr, file_size)
                )
                break

            match = self.lz_match_getter(input_data, lz_seeker, file_size)
            if match is None:
                lz_seeker += 1
                continue

            if lz_seeker > encoding_ptr:
                output.extend(
                    self.encode_literal(input_data, encoding_ptr, lz_seeker)
                )

            entry_length, lookback = match
            output.append(entry_length + 0x7D)
            output.append(~lookback)

            lz_seeker += entry_length
            encoding_ptr = lz_seeker

        total_size = len(output) + 12
        return b''.join((
            LZ77_MAGIC,
            total_size.to_bytes(4, 'little'),
            file_size.to_bytes(4, 'little'),
            output,
        ))


class NonOverlappingLZ77Compressor:
    """Conservative encoder for decoders that cannot copy overlapping matches.

    The resource format is unchanged.  Every back-reference is restricted to
    ``match_length <= distance``, so its source bytes are all present before
    the decoder starts copying the match.
    """

    @staticmethod
    def _encode_literals(output: bytearray, literals: bytearray) -> None:
        for position in range(0, len(literals), 0x80):
            entry = literals[position:position + 0x80]
            output.append(len(entry) - 1)
            output.extend(entry)
        literals.clear()

    def compress(self, input_data: bytes) -> bytes:
        input_data = bytes(input_data)
        output = bytearray()
        literals = bytearray()
        position = 0

        while position < len(input_data):
            best_length = 0
            best_distance = 0

            for distance in range(1, min(0x100, position) + 1):
                maximum = min(0x82, distance, len(input_data) - position)
                if maximum < 3:
                    continue
                if input_data[position] != input_data[position - distance]:
                    continue

                length = 1
                while (
                    length < maximum
                    and input_data[position + length]
                    == input_data[position - distance + length]
                ):
                    length += 1

                if length > best_length:
                    best_length = length
                    best_distance = distance

            if best_length >= 3:
                self._encode_literals(output, literals)
                output.append(best_length + 0x7D)
                output.append(best_distance - 1)
                position += best_length
            else:
                literals.append(input_data[position])
                position += 1
                if len(literals) == 0x80:
                    self._encode_literals(output, literals)

        self._encode_literals(output, literals)
        total_size = len(output) + 12
        return b''.join((
            LZ77_MAGIC,
            total_size.to_bytes(4, 'little'),
            len(input_data).to_bytes(4, 'little'),
            output,
        ))


class RLECompressor:
    """Compress bytes using SMT if's 0x01/0x01 RLE resource format."""

    @staticmethod
    def _repeat_length(data: bytes, position: int) -> int:
        maximum = min(0x82, len(data) - position)
        length = 1
        while length < maximum and data[position + length] == data[position]:
            length += 1
        return length

    def compress(self, input_data: bytes) -> bytes:
        input_data = bytes(input_data)
        output = bytearray()
        literals = bytearray()
        position = 0

        def flush_literals() -> None:
            for start in range(0, len(literals), 0x80):
                entry = literals[start:start + 0x80]
                output.append(len(entry) - 1)
                output.extend(entry)
            literals.clear()

        while position < len(input_data):
            repeat_length = self._repeat_length(input_data, position)
            if repeat_length >= 3:
                flush_literals()
                output.append(repeat_length + 0x7D)
                output.append(input_data[position])
                position += repeat_length
            else:
                literals.append(input_data[position])
                position += 1
                if len(literals) == 0x80:
                    flush_literals()

        flush_literals()
        total_size = len(output) + 12
        return b''.join((
            RLE_MAGIC,
            total_size.to_bytes(4, 'little'),
            len(input_data).to_bytes(4, 'little'),
            output,
        ))


def compress_lz77(input_data: bytes) -> bytes:
    return LZ77Compressor().compress(input_data)


def compress_lz77_non_overlapping(input_data: bytes) -> bytes:
    return NonOverlappingLZ77Compressor().compress(input_data)


def compress_rle(input_data: bytes) -> bytes:
    return RLECompressor().compress(input_data)


def pack_uncompressed(input_data: bytes) -> bytes:
    """Return a complete 0x01/0x00 uncompressed resource."""
    input_data = bytes(input_data)
    total_size = len(input_data) + 8
    return b''.join((
        RAW_MAGIC,
        total_size.to_bytes(4, 'little'),
        input_data,
    ))


def decompress_resource(resource: bytes) -> bytes:
    """Decompress 0x01/0x00, 0x01/0x01, or 0x01/0x02 resource data."""
    resource = bytes(resource)
    if len(resource) < 8:
        raise ValueError('Resource is shorter than its 8-byte base header')

    resource_header = resource[:4]
    magic = resource_header[:2] + b'\x00\x00'
    total_size = int.from_bytes(resource[4:8], 'little')
    if total_size < 8 or total_size > len(resource):
        raise ValueError(
            f'Invalid declared resource size {total_size}; buffer has '
            f'{len(resource)} bytes'
        )

    if magic == RAW_MAGIC:
        return resource[8:total_size]
    if magic not in {RLE_MAGIC, LZ77_MAGIC}:
        raise ValueError(
            f'Unsupported resource magic: {resource_header.hex().upper()}'
        )
    if total_size < 12:
        raise ValueError('Compressed resource is shorter than its 12-byte header')

    expected_size = int.from_bytes(resource[8:12], 'little')
    source = memoryview(resource)[12:total_size]
    source_position = 0
    output = bytearray()

    while len(output) < expected_size:
        if source_position >= len(source):
            raise ValueError('Compressed stream ended before reaching output size')

        control = source[source_position]
        source_position += 1

        if control < 0x80:
            length = control + 1
            end = source_position + length
            if end > len(source):
                raise ValueError('Literal token exceeds compressed stream')
            output.extend(source[source_position:end])
            source_position = end
        else:
            length = control - 0x7D
            if source_position >= len(source):
                raise ValueError('Back-reference token has no distance byte')

            value = source[source_position]
            source_position += 1

            if magic == RLE_MAGIC:
                output.extend(bytes([value]) * length)
            else:
                distance = value + 1
                if distance > len(output):
                    raise ValueError(
                        f'Invalid LZ77 distance {distance} at output offset '
                        f'{len(output)}'
                    )
                for _ in range(length):
                    output.append(output[-distance])

        if len(output) > expected_size:
            raise ValueError(
                f'Decompressed data exceeded expected size {expected_size}'
            )

    return bytes(output)


def verify_lz77_roundtrip(input_data: bytes) -> bytes:
    compressed = compress_lz77(input_data)
    decompressed = decompress_resource(compressed)
    if decompressed != bytes(input_data):
        raise AssertionError('LZ77 compression roundtrip failed')
    return compressed


def expand_lz77_to_size(resource: bytes, target_size: int) -> bytes:
    """Retokenize an LZ77 stream to an exact larger declared size.

    Selected two-byte back-references are replaced by equivalent literal
    tokens.  The decompressed bytes and all untouched tokens remain exactly
    the same.  This is useful for diagnosing loaders that may depend on the
    original compressed block length.
    """
    resource = bytes(resource)
    if resource[:4] != LZ77_MAGIC:
        raise ValueError('Only 0x01/0x02 LZ77 resources can be expanded')

    current_size = int.from_bytes(resource[4:8], 'little')
    if target_size < current_size:
        raise ValueError('Target size must not be smaller than the stream')
    if target_size > len(resource):
        raise ValueError('Target size exceeds the supplied resource buffer')
    if target_size == current_size:
        return resource[:current_size]

    raw_data = decompress_resource(resource)
    tokens = []
    source_position = 12
    output_position = 0

    while source_position < current_size:
        token_start = source_position
        control = resource[source_position]
        source_position += 1

        if control < 0x80:
            output_length = control + 1
            source_position += output_length
            is_reference = False
        else:
            output_length = control - 0x7D
            source_position += 1
            is_reference = True

        if source_position > current_size:
            raise ValueError('Token exceeds the declared compressed stream')
        tokens.append((
            resource[token_start:source_position],
            output_position,
            output_length,
            is_reference,
        ))
        output_position += output_length

    if source_position != current_size or output_position != len(raw_data):
        raise ValueError('LZ77 token stream does not end at its declared size')

    required_growth = target_size - current_size
    parents = [None] * (required_growth + 1)
    parents[0] = (-1, -1)

    for token_index, (_, _, length, is_reference) in enumerate(tokens):
        # A reference is two bytes.  One literal token of length N is N+1
        # bytes, so replacing it grows the stream by N-1 bytes.
        if not is_reference or length > 0x80:
            continue
        growth = length - 1
        for subtotal in range(required_growth - growth, -1, -1):
            if parents[subtotal] is None:
                continue
            new_total = subtotal + growth
            if parents[new_total] is None:
                parents[new_total] = (subtotal, token_index)

    if parents[required_growth] is None:
        raise ValueError(
            f'Cannot expand stream by exactly {required_growth} bytes'
        )

    replacements = set()
    subtotal = required_growth
    while subtotal:
        previous, token_index = parents[subtotal]
        replacements.add(token_index)
        subtotal = previous

    body = bytearray()
    for token_index, (encoded, raw_offset, length, _) in enumerate(tokens):
        if token_index not in replacements:
            body.extend(encoded)
            continue
        body.append(length - 1)
        body.extend(raw_data[raw_offset:raw_offset + length])

    expanded = b''.join((
        LZ77_MAGIC,
        target_size.to_bytes(4, 'little'),
        len(raw_data).to_bytes(4, 'little'),
        body,
    ))
    if len(expanded) != target_size:
        raise AssertionError(
            f'Expanded stream is {len(expanded)} bytes, expected {target_size}'
        )
    if decompress_resource(expanded) != raw_data:
        raise AssertionError('Expanded stream changed decompressed data')
    return expanded


def expand_rle_to_size(resource: bytes, target_size: int) -> bytes:
    """Retokenize an RLE stream to an exact larger declared size.

    A literal run of ``N`` bytes occupies ``N + 1`` bytes.  Splitting that
    run into multiple literal tokens adds one byte per split without changing
    the decompressed data.  This gives graphic resources a safe way to retain
    their original declared size and, consequently, the fixed offsets of
    palettes or other resources stored after the main image.
    """
    resource = bytes(resource)
    if resource[:4] != RLE_MAGIC:
        raise ValueError('Only 0x01/0x01 RLE resources can be expanded')

    current_size = int.from_bytes(resource[4:8], 'little')
    if current_size > len(resource):
        raise ValueError('Declared RLE size exceeds the supplied buffer')
    if target_size < current_size:
        raise ValueError('Target size must not be smaller than the stream')
    if target_size == current_size:
        return resource[:current_size]

    raw_data = decompress_resource(resource)
    tokens = []
    source_position = 12
    output_position = 0
    split_capacity = 0

    while source_position < current_size:
        control = resource[source_position]
        source_position += 1

        if control < 0x80:
            length = control + 1
            end = source_position + length
            if end > current_size:
                raise ValueError('Literal token exceeds the declared RLE stream')
            literal = resource[source_position:end]
            tokens.append(('literal', literal))
            split_capacity += length - 1
            source_position = end
        else:
            length = control - 0x7D
            if source_position >= current_size:
                raise ValueError('Repeat token has no value byte')
            value = resource[source_position]
            source_position += 1
            tokens.append(('repeat', bytes((control, value))))

        output_position += length

    if source_position != current_size or output_position != len(raw_data):
        raise ValueError('RLE token stream does not end at its declared size')

    required_growth = target_size - current_size
    if required_growth > split_capacity:
        raise ValueError(
            f'Cannot expand RLE stream by {required_growth} bytes; '
            f'literal split capacity is {split_capacity}'
        )

    body = bytearray()
    remaining_growth = required_growth

    for token_type, encoded in tokens:
        if token_type == 'repeat':
            body.extend(encoded)
            continue

        split_count = min(remaining_growth, len(encoded) - 1)

        # Emit one-byte literal tokens for each requested split, followed by
        # the unsplit remainder.  This grows the stream by split_count bytes.
        for value in encoded[:split_count]:
            body.extend((0, value))

        remainder = encoded[split_count:]
        if remainder:
            body.append(len(remainder) - 1)
            body.extend(remainder)

        remaining_growth -= split_count

    if remaining_growth:
        raise AssertionError('RLE expansion did not consume the requested growth')

    expanded = b''.join((
        resource[:4],
        target_size.to_bytes(4, 'little'),
        len(raw_data).to_bytes(4, 'little'),
        body,
    ))
    if len(expanded) != target_size:
        raise AssertionError(
            f'Expanded RLE stream is {len(expanded)} bytes, '
            f'expected {target_size}'
        )
    if decompress_resource(expanded) != raw_data:
        raise AssertionError('Expanded RLE stream changed decompressed data')
    return expanded


def _selftest() -> None:
    samples = (
        b'',
        b'A',
        b'AB' * 200,
        bytes(range(256)) * 4,
        b'1234567890' * 1000,
    )

    for sample in samples:
        verify_lz77_roundtrip(sample)
        assert decompress_resource(pack_uncompressed(sample)) == sample

    rle_sample = bytes(range(128)) * 2
    rle_resource = compress_rle(rle_sample)
    expanded_rle = expand_rle_to_size(rle_resource, len(rle_resource) + 17)
    assert decompress_resource(expanded_rle) == rle_sample

    print('compression self-test passed')


if __name__ == '__main__':
    _selftest()
