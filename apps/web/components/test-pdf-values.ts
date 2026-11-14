import type { DocumentTextReference } from "@tire/domain-types";

export function testPdfReference(value: unknown): DocumentTextReference | null {
  if (!value || typeof value !== "object" || !("pdf_reference" in value) || value.pdf_reference === undefined) return null;
  const reference = value.pdf_reference;
  if (!reference || typeof reference !== "object" || Array.isArray(reference)) throw new Error("成绩 PDF 引用格式无效，请重新读取记录。");
  const record = reference as Record<string, unknown>;
  const keys = ["document_id", "document_fingerprint", "raw_hash", "extractor_version", "page", "start", "end", "chunk_id"];
  const hash = (item: unknown) => typeof item === "string" && /^[a-f0-9]{64}$/.test(item);
  const integer = (item: unknown, minimum: number, maximum: number) => typeof item === "number" && Number.isInteger(item) && item >= minimum && item <= maximum;
  if (Object.keys(record).length !== keys.length || keys.some(key => !Object.hasOwn(record, key))
      || typeof record.document_id !== "string" || !record.document_id.length || record.document_id.length > 64
      || typeof record.extractor_version !== "string" || !record.extractor_version.length || record.extractor_version.length > 100
      || !hash(record.document_fingerprint) || !hash(record.raw_hash) || !hash(record.chunk_id)
      || !integer(record.page, 1, 2000) || !integer(record.start, 0, 100000) || !integer(record.end, 1, 100000)
      || (record.end as number) <= (record.start as number)) throw new Error("成绩 PDF 引用格式无效，请重新读取记录。");
  return reference as DocumentTextReference;
}
