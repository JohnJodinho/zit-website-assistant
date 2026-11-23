const frameAncestors = process.env.FRAME_ANCESTORS || "'none'";
const headers = `/*
  Content-Security-Policy: frame-ancestors ${frameAncestors};
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
`;
console.log(headers.trim());
