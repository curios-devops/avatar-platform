/**
 * Gaussian Splat Loader — binary little-endian PLY.
 * Parses property names from the header so adding new properties
 * (e.g. triangle_idx, bary_*) never breaks the reader.
 */

import { GaussianData } from '../../../shared/types';

type PropType = 'float' | 'int' | 'uint' | 'double' | 'uchar' | 'short' | 'ushort';

interface PropDef {
  name: string;
  type: PropType;
  byteSize: number;
  offset: number; // byte offset within one vertex record
}

const TYPE_SIZES: Record<PropType, number> = {
  float: 4, double: 8, int: 4, uint: 4,
  uchar: 1, short: 2, ushort: 2,
};

export class SplatLoader {
  async loadFromURL(url: string): Promise<GaussianData> {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`PLY fetch failed: ${response.status}`);
    const buffer = await response.arrayBuffer();
    return this.parsePLY(buffer);
  }

  private parsePLY(buffer: ArrayBuffer): GaussianData {
    const bytes = new Uint8Array(buffer);

    // ── locate end_header ───────────────────────────────────────────────────
    const END = 'end_header\n';
    let headerEnd = -1;
    for (let i = 0; i < bytes.length - END.length; i++) {
      if (bytes[i] === 0x65 /* 'e' */ && this._matchStr(bytes, i, END)) {
        headerEnd = i + END.length;
        break;
      }
    }
    if (headerEnd === -1) throw new Error('Invalid PLY: no end_header');

    const header = new TextDecoder().decode(bytes.slice(0, headerEnd));
    const lines  = header.split('\n').map(l => l.trim()).filter(Boolean);

    if (!lines[0].startsWith('ply')) throw new Error('Not a PLY file');

    const formatLine = lines.find(l => l.startsWith('format'));
    if (!formatLine?.includes('binary_little_endian'))
      throw new Error('Only binary_little_endian PLY is supported');

    const vertexLine = lines.find(l => l.startsWith('element vertex'));
    if (!vertexLine) throw new Error('PLY has no vertex element');
    const vertexCount = parseInt(vertexLine.split(' ')[2]);

    // ── parse properties ────────────────────────────────────────────────────
    const props: PropDef[] = [];
    let offset = 0;
    let inVertex = false;
    for (const line of lines) {
      if (line.startsWith('element vertex')) { inVertex = true; continue; }
      if (line.startsWith('element') && !line.startsWith('element vertex')) { inVertex = false; continue; }
      if (inVertex && line.startsWith('property')) {
        const parts = line.split(' ');
        const type  = parts[1] as PropType;
        const name  = parts[2];
        const size  = TYPE_SIZES[type] ?? 4;
        props.push({ name, type, byteSize: size, offset });
        offset += size;
      }
    }

    const bytesPerVertex = offset;

    // ── build index of needed properties ────────────────────────────────────
    const idx = (name: string) => props.findIndex(p => p.name === name);

    const iX   = idx('x');   const iY   = idx('y');   const iZ   = idx('z');
    const iDC0 = idx('f_dc_0'); const iDC1 = idx('f_dc_1'); const iDC2 = idx('f_dc_2');
    const iOpa = idx('opacity');
    const iS0  = idx('scale_0'); const iS1 = idx('scale_1'); const iS2 = idx('scale_2');
    const iR0  = idx('rot_0'); const iR1 = idx('rot_1'); const iR2 = idx('rot_2'); const iR3 = idx('rot_3');

    if ([iX, iY, iZ, iOpa, iS0, iS1, iS2, iR0, iR1, iR2, iR3].includes(-1))
      throw new Error('PLY missing required Gaussian properties');

    // ── allocate output arrays ──────────────────────────────────────────────
    const positions  = new Float32Array(vertexCount * 3);
    const scales     = new Float32Array(vertexCount * 3);
    const rotations  = new Float32Array(vertexCount * 4);
    const colors     = new Float32Array(vertexCount * 4);
    const opacities  = new Float32Array(vertexCount);

    const view = new DataView(buffer, headerEnd);

    const readF = (vOff: number, prop: PropDef) =>
      view.getFloat32(vOff + prop.offset, true);

    // ── decode each vertex ──────────────────────────────────────────────────
    for (let i = 0; i < vertexCount; i++) {
      const vOff = i * bytesPerVertex;

      positions[i * 3]     = readF(vOff, props[iX]);
      positions[i * 3 + 1] = readF(vOff, props[iY]);
      positions[i * 3 + 2] = readF(vOff, props[iZ]);

      // SH-DC → linear RGB (SH DC coefficient * 2√π ≈ * 3.5449)
      if (iDC0 !== -1) {
        const SH_C0 = 0.28209479177387814;
        colors[i * 4]     = Math.max(0, Math.min(1, readF(vOff, props[iDC0]) * SH_C0 + 0.5));
        colors[i * 4 + 1] = Math.max(0, Math.min(1, readF(vOff, props[iDC1]) * SH_C0 + 0.5));
        colors[i * 4 + 2] = Math.max(0, Math.min(1, readF(vOff, props[iDC2]) * SH_C0 + 0.5));
      } else {
        colors[i * 4] = colors[i * 4 + 1] = colors[i * 4 + 2] = 0.8;
      }

      const rawOpacity  = readF(vOff, props[iOpa]);
      opacities[i]      = 1.0 / (1.0 + Math.exp(-rawOpacity)); // sigmoid
      colors[i * 4 + 3] = opacities[i];

      scales[i * 3]     = Math.exp(readF(vOff, props[iS0]));
      scales[i * 3 + 1] = Math.exp(readF(vOff, props[iS1]));
      scales[i * 3 + 2] = Math.exp(readF(vOff, props[iS2]));

      rotations[i * 4]     = readF(vOff, props[iR0]);
      rotations[i * 4 + 1] = readF(vOff, props[iR1]);
      rotations[i * 4 + 2] = readF(vOff, props[iR2]);
      rotations[i * 4 + 3] = readF(vOff, props[iR3]);
    }

    return { positions, scales, rotations, colors, opacities, count: vertexCount };
  }

  private _matchStr(bytes: Uint8Array, start: number, str: string): boolean {
    for (let i = 0; i < str.length; i++) {
      if (bytes[start + i] !== str.charCodeAt(i)) return false;
    }
    return true;
  }
}
