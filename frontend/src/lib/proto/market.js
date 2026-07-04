// ES Module — 直接导入 protobufjs
import $protobuf from 'protobufjs/minimal';

const $Reader = $protobuf.Reader, $Writer = $protobuf.Writer, $util = $protobuf.util;
const $root = $protobuf.roots["default"] || ($protobuf.roots["default"] = {});

$root.market = (function() {
    var market = {};
        market.Order = (function() {
            function Order(properties) {
                if (properties)
                    for (var keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }
            Order.prototype.price = 0;
            Order.prototype.size = 0;
            Order.create = function create(properties) { return new Order(properties); };
            Order.encode = function encode(message, writer, q) {
                if (!writer) writer = $Writer.create();
                if (q === undefined) q = 0;
                if (q > $util.recursionLimit) throw Error("max depth exceeded");
                if (message.price != null && Object.hasOwnProperty.call(message, "price"))
                    writer.uint32(13).float(message.price);
                if (message.size != null && Object.hasOwnProperty.call(message, "size"))
                    writer.uint32(21).float(message.size);
                if (message.$unknowns != null && Object.hasOwnProperty.call(message, "$unknowns"))
                    for (var i = 0; i < message.$unknowns.length; ++i)
                        writer.raw(message.$unknowns[i]);
                return writer;
            };
            Order.encodeDelimited = function encodeDelimited(message, writer) {
                return this.encode(message, writer && writer.len ? writer.fork() : writer).ldelim();
            };
            Order.decode = function decode(reader, length, z, q, g) {
                if (!(reader instanceof $Reader)) reader = $Reader.create(reader);
                if (q === undefined) q = 0;
                if (q > $Reader.recursionLimit) throw Error("max depth exceeded");
                var end = length === undefined ? reader.len : reader.pos + length, message = g || new Order(), v;
                while (reader.pos < end) {
                    var s = reader.pos;
                    var tag = reader.tag();
                    if (tag === z) { z = undefined; break; }
                    var u = tag & 7;
                    switch (tag >>>= 3) {
                    case 1: if (u !== 5) break; if ((v = reader.float()) !== 0) message.price = v; else delete message.price; continue;
                    case 2: if (u !== 5) break; if ((v = reader.float()) !== 0) message.size = v; else delete message.size; continue;
                    }
                    reader.skipType(u, q, tag);
                    if (!reader.discardUnknown) {
                        $util.makeProp(message, "$unknowns", false);
                        (message.$unknowns || (message.$unknowns = [])).push(reader.raw(s, reader.pos));
                    }
                }
                if (z !== undefined) throw Error("missing end group");
                return message;
            };
            Order.decodeDelimited = function decodeDelimited(reader) {
                if (!(reader instanceof $Reader)) reader = new $Reader(reader);
                return this.decode(reader, reader.uint32());
            };
            Order.verify = function verify(message, q) {
                if (typeof message !== "object" || message === null) return "object expected";
                if (q === undefined) q = 0;
                if (q > $util.recursionLimit) return "max depth exceeded";
                if (message.price != null && Object.hasOwnProperty.call(message, "price"))
                    if (typeof message.price !== "number") return "price: number expected";
                if (message.size != null && Object.hasOwnProperty.call(message, "size"))
                    if (typeof message.size !== "number") return "size: number expected";
                return null;
            };
            Order.fromObject = function fromObject(object, q) {
                if (object instanceof Order) return object;
                if (!$util.isObject(object)) throw TypeError(".market.Order: object expected");
                if (q === undefined) q = 0;
                if (q > $util.recursionLimit) throw Error("max depth exceeded");
                var message = new Order();
                if (object.price != null) if (Number(object.price) !== 0) message.price = Number(object.price);
                if (object.size != null) if (Number(object.size) !== 0) message.size = Number(object.size);
                return message;
            };
            Order.toObject = function toObject(message, options, q) {
                if (!options) options = {};
                if (q === undefined) q = 0;
                if (q > $util.recursionLimit) throw Error("max depth exceeded");
                var object = {};
                if (options.defaults) { object.price = 0; object.size = 0; }
                if (message.price != null && Object.hasOwnProperty.call(message, "price"))
                    object.price = options.json && !isFinite(message.price) ? String(message.price) : message.price;
                if (message.size != null && Object.hasOwnProperty.call(message, "size"))
                    object.size = options.json && !isFinite(message.size) ? String(message.size) : message.size;
                return object;
            };
            Order.prototype.toJSON = function toJSON() {
                return this.constructor.toObject(this, $protobuf.util.toJSONOptions);
            };
            Order.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) typeUrlPrefix = "type.googleapis.com";
                return typeUrlPrefix + "/market.Order";
            };
            return Order;
        })();
        market.QuoteData = (function() {
            function QuoteData(properties) {
                this.bids = [];
                this.asks = [];
                if (properties)
                    for (var keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }
            QuoteData.prototype.status = "";
            QuoteData.prototype.ticker = "";
            QuoteData.prototype.lastPrice = 0;
            QuoteData.prototype.changePct = "";
            QuoteData.prototype.volumeStr = "";
            QuoteData.prototype.bids = $util.emptyArray;
            QuoteData.prototype.asks = $util.emptyArray;
            QuoteData.prototype.source = "";
            QuoteData.create = function create(properties) { return new QuoteData(properties); };
            QuoteData.encode = function encode(message, writer, q) {
                if (!writer) writer = $Writer.create();
                if (q === undefined) q = 0;
                if (q > $util.recursionLimit) throw Error("max depth exceeded");
                if (message.status != null && Object.hasOwnProperty.call(message, "status"))
                    writer.uint32(10).string(message.status);
                if (message.ticker != null && Object.hasOwnProperty.call(message, "ticker"))
                    writer.uint32(18).string(message.ticker);
                if (message.lastPrice != null && Object.hasOwnProperty.call(message, "lastPrice"))
                    writer.uint32(29).float(message.lastPrice);
                if (message.changePct != null && Object.hasOwnProperty.call(message, "changePct"))
                    writer.uint32(34).string(message.changePct);
                if (message.volumeStr != null && Object.hasOwnProperty.call(message, "volumeStr"))
                    writer.uint32(42).string(message.volumeStr);
                if (message.bids != null && message.bids.length)
                    for (var i = 0; i < message.bids.length; ++i)
                        $root.market.Order.encode(message.bids[i], writer.uint32(50).fork(), q + 1).ldelim();
                if (message.asks != null && message.asks.length)
                    for (var i = 0; i < message.asks.length; ++i)
                        $root.market.Order.encode(message.asks[i], writer.uint32(58).fork(), q + 1).ldelim();
                if (message.source != null && Object.hasOwnProperty.call(message, "source"))
                    writer.uint32(66).string(message.source);
                if (message.$unknowns != null && Object.hasOwnProperty.call(message, "$unknowns"))
                    for (var i = 0; i < message.$unknowns.length; ++i)
                        writer.raw(message.$unknowns[i]);
                return writer;
            };
            QuoteData.encodeDelimited = function encodeDelimited(message, writer) {
                return this.encode(message, writer && writer.len ? writer.fork() : writer).ldelim();
            };
            QuoteData.decode = function decode(reader, length, z, q, g) {
                if (!(reader instanceof $Reader)) reader = $Reader.create(reader);
                if (q === undefined) q = 0;
                if (q > $Reader.recursionLimit) throw Error("max depth exceeded");
                var end = length === undefined ? reader.len : reader.pos + length, message = g || new QuoteData(), v;
                while (reader.pos < end) {
                    var s = reader.pos;
                    var tag = reader.tag();
                    if (tag === z) { z = undefined; break; }
                    var u = tag & 7;
                    switch (tag >>>= 3) {
                    case 1: if (u !== 2) break; if ((v = reader.string()).length) message.status = v; else delete message.status; continue;
                    case 2: if (u !== 2) break; if ((v = reader.string()).length) message.ticker = v; else delete message.ticker; continue;
                    case 3: if (u !== 5) break; if ((v = reader.float()) !== 0) message.lastPrice = v; else delete message.lastPrice; continue;
                    case 4: if (u !== 2) break; if ((v = reader.string()).length) message.changePct = v; else delete message.changePct; continue;
                    case 5: if (u !== 2) break; if ((v = reader.string()).length) message.volumeStr = v; else delete message.volumeStr; continue;
                    case 6: if (u !== 2) break; if (!(message.bids && message.bids.length)) message.bids = []; message.bids.push($root.market.Order.decode(reader, reader.uint32(), undefined, q + 1)); continue;
                    case 7: if (u !== 2) break; if (!(message.asks && message.asks.length)) message.asks = []; message.asks.push($root.market.Order.decode(reader, reader.uint32(), undefined, q + 1)); continue;
                    case 8: if (u !== 2) break; if ((v = reader.string()).length) message.source = v; else delete message.source; continue;
                    }
                    reader.skipType(u, q, tag);
                    if (!reader.discardUnknown) {
                        $util.makeProp(message, "$unknowns", false);
                        (message.$unknowns || (message.$unknowns = [])).push(reader.raw(s, reader.pos));
                    }
                }
                if (z !== undefined) throw Error("missing end group");
                return message;
            };
            QuoteData.decodeDelimited = function decodeDelimited(reader) {
                if (!(reader instanceof $Reader)) reader = new $Reader(reader);
                return this.decode(reader, reader.uint32());
            };
            QuoteData.verify = function verify(message, q) {
                if (typeof message !== "object" || message === null) return "object expected";
                if (q === undefined) q = 0;
                if (q > $util.recursionLimit) return "max depth exceeded";
                if (message.status != null && Object.hasOwnProperty.call(message, "status"))
                    if (!$util.isString(message.status)) return "status: string expected";
                if (message.ticker != null && Object.hasOwnProperty.call(message, "ticker"))
                    if (!$util.isString(message.ticker)) return "ticker: string expected";
                if (message.lastPrice != null && Object.hasOwnProperty.call(message, "lastPrice"))
                    if (typeof message.lastPrice !== "number") return "lastPrice: number expected";
                if (message.changePct != null && Object.hasOwnProperty.call(message, "changePct"))
                    if (!$util.isString(message.changePct)) return "changePct: string expected";
                if (message.volumeStr != null && Object.hasOwnProperty.call(message, "volumeStr"))
                    if (!$util.isString(message.volumeStr)) return "volumeStr: string expected";
                if (message.bids != null && Object.hasOwnProperty.call(message, "bids")) {
                    if (!Array.isArray(message.bids)) return "bids: array expected";
                    for (var i = 0; i < message.bids.length; ++i) {
                        var error = $root.market.Order.verify(message.bids[i], q + 1);
                        if (error) return "bids." + error;
                    }
                }
                if (message.asks != null && Object.hasOwnProperty.call(message, "asks")) {
                    if (!Array.isArray(message.asks)) return "asks: array expected";
                    for (var i = 0; i < message.asks.length; ++i) {
                        var error = $root.market.Order.verify(message.asks[i], q + 1);
                        if (error) return "asks." + error;
                    }
                }
                if (message.source != null && Object.hasOwnProperty.call(message, "source"))
                    if (!$util.isString(message.source)) return "source: string expected";
                return null;
            };
            QuoteData.fromObject = function fromObject(object, q) {
                if (object instanceof QuoteData) return object;
                if (!$util.isObject(object)) throw TypeError(".market.QuoteData: object expected");
                if (q === undefined) q = 0;
                if (q > $util.recursionLimit) throw Error("max depth exceeded");
                var message = new QuoteData();
                if (object.status != null) if (typeof object.status !== "string" || object.status.length) message.status = String(object.status);
                if (object.ticker != null) if (typeof object.ticker !== "string" || object.ticker.length) message.ticker = String(object.ticker);
                if (object.lastPrice != null) if (Number(object.lastPrice) !== 0) message.lastPrice = Number(object.lastPrice);
                if (object.changePct != null) if (typeof object.changePct !== "string" || object.changePct.length) message.changePct = String(object.changePct);
                if (object.volumeStr != null) if (typeof object.volumeStr !== "string" || object.volumeStr.length) message.volumeStr = String(object.volumeStr);
                if (object.bids) {
                    if (!Array.isArray(object.bids)) throw TypeError(".market.QuoteData.bids: array expected");
                    message.bids = Array(object.bids.length);
                    for (var i = 0; i < object.bids.length; ++i) {
                        if (!$util.isObject(object.bids[i])) throw TypeError(".market.QuoteData.bids: object expected");
                        message.bids[i] = $root.market.Order.fromObject(object.bids[i], q + 1);
                    }
                }
                if (object.asks) {
                    if (!Array.isArray(object.asks)) throw TypeError(".market.QuoteData.asks: array expected");
                    message.asks = Array(object.asks.length);
                    for (var i = 0; i < object.asks.length; ++i) {
                        if (!$util.isObject(object.asks[i])) throw TypeError(".market.QuoteData.asks: object expected");
                        message.asks[i] = $root.market.Order.fromObject(object.asks[i], q + 1);
                    }
                }
                if (object.source != null) if (typeof object.source !== "string" || object.source.length) message.source = String(object.source);
                return message;
            };
            QuoteData.toObject = function toObject(message, options, q) {
                if (!options) options = {};
                if (q === undefined) q = 0;
                if (q > $util.recursionLimit) throw Error("max depth exceeded");
                var object = {};
                if (options.arrays || options.defaults) { object.bids = []; object.asks = []; }
                if (options.defaults) { object.status = ""; object.ticker = ""; object.lastPrice = 0; object.changePct = ""; object.volumeStr = ""; object.source = ""; }
                if (message.status != null && Object.hasOwnProperty.call(message, "status")) object.status = message.status;
                if (message.ticker != null && Object.hasOwnProperty.call(message, "ticker")) object.ticker = message.ticker;
                if (message.lastPrice != null && Object.hasOwnProperty.call(message, "lastPrice"))
                    object.lastPrice = options.json && !isFinite(message.lastPrice) ? String(message.lastPrice) : message.lastPrice;
                if (message.changePct != null && Object.hasOwnProperty.call(message, "changePct")) object.changePct = message.changePct;
                if (message.volumeStr != null && Object.hasOwnProperty.call(message, "volumeStr")) object.volumeStr = message.volumeStr;
                if (message.bids && message.bids.length) {
                    object.bids = Array(message.bids.length);
                    for (var j = 0; j < message.bids.length; ++j)
                        object.bids[j] = $root.market.Order.toObject(message.bids[j], options, q + 1);
                }
                if (message.asks && message.asks.length) {
                    object.asks = Array(message.asks.length);
                    for (var j = 0; j < message.asks.length; ++j)
                        object.asks[j] = $root.market.Order.toObject(message.asks[j], options, q + 1);
                }
                if (message.source != null && Object.hasOwnProperty.call(message, "source")) object.source = message.source;
                return object;
            };
            QuoteData.prototype.toJSON = function toJSON() {
                return this.constructor.toObject(this, $protobuf.util.toJSONOptions);
            };
            QuoteData.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) typeUrlPrefix = "type.googleapis.com";
                return typeUrlPrefix + "/market.QuoteData";
            };
            return QuoteData;
        })();
    return market;
})();

export default $root;
export const market = $root.market;
